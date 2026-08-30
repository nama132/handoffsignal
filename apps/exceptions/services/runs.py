"""Detector runs: claim, evaluate, persist cases, finish.

Section 22.5: a DetectorRun is claimed with an atomic state/expiry predicate; only the
current owner may heartbeat or finish; a new worker may reclaim only after
`leased_until`, incrementing `attempt_count`, and continues idempotently against the
same immutable manifest.

Section 19: "A source import can be replayed without duplicate cases." Cases dedup on
fingerprint; a repeated evaluation refreshes rather than duplicates.
"""

from __future__ import annotations

import datetime as dt
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit import models as audit
from apps.exceptions.detectors import revenue_unbilled
from apps.exceptions.detectors.base import DetectionResult, DetectorOutput
from apps.exceptions.models import (
    CaseState,
    DetectorRun,
    ExceptionCase,
    ExceptionEvent,
    ExceptionSourceLink,
    ExceptionType,
)
from apps.exceptions.services import financial
from apps.ingestion.models import ReconciliationRun, SourceRecordVersion

LEASE_SECONDS = 300

DETECTORS = {revenue_unbilled.RULE_CODE: revenue_unbilled}


class NotLeaseOwner(RuntimeError):
    pass


def _owner_id() -> str:
    import os
    import socket

    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


@transaction.atomic
def claim(
    *, run: ReconciliationRun, detector_code: str, rule_version: int, as_of: dt.datetime
) -> DetectorRun | None:
    """Claim (or reclaim) the evaluation for this manifest. Returns None if held.

    The INSERT is guarded by the unique evaluation key; the reclaim is guarded by the
    expiry predicate in the UPDATE. Two concurrent claimers cannot both succeed.
    """
    now = timezone.now()
    owner = _owner_id()
    until = now + dt.timedelta(seconds=LEASE_SECONDS)

    try:
        with transaction.atomic():
            return DetectorRun.objects.create(
                organization=run.organization,
                reconciliation_run=run,
                detector_code=detector_code,
                rule_version=rule_version,
                as_of=as_of,
                input_manifest_sha256=run.input_manifest_sha256,
                lease_owner_id=owner,
                leased_until=until,
                heartbeat_at=now,
                attempt_count=1,
            )
    except IntegrityError:
        pass  # an evaluation row already exists; fall through to the reclaim path

    # Reclaim only if terminal-and-failed is not the state, and the lease has expired.
    # Reclaimable: a RUNNING row whose lease expired (crashed worker), or a FAILED row
    # at any time (the visible failed-job recovery path, section 19 line 711).
    from django.db.models import Q

    updated = (
        DetectorRun.objects.filter(
            organization=run.organization,
            reconciliation_run=run,
            detector_code=detector_code,
            rule_version=rule_version,
            input_manifest_sha256=run.input_manifest_sha256,
        )
        .filter(
            Q(status=DetectorRun.Status.RUNNING, leased_until__lt=now)
            | Q(status=DetectorRun.Status.FAILED)
        )
        .update(
            status=DetectorRun.Status.RUNNING,
            finished_at=None,
            failure_code="",
            failure_summary="",
            lease_owner_id=owner,
            leased_until=until,
            heartbeat_at=now,
            attempt_count=models_F("attempt_count") + 1,
        )
    )
    existing = DetectorRun.objects.get(
        organization=run.organization,
        reconciliation_run=run,
        detector_code=detector_code,
        rule_version=rule_version,
        input_manifest_sha256=run.input_manifest_sha256,
    )
    if updated == 1:
        return existing
    # A SUCCEEDED evaluation is returned as-is so at-least-once delivery converges on
    # the same row; a live lease held by another worker is the only "nothing to do".
    return existing if existing.status == DetectorRun.Status.SUCCEEDED else None


def models_F(name: str):
    from django.db.models import F

    return F(name)


def heartbeat(detector_run: DetectorRun) -> None:
    now = timezone.now()
    updated = DetectorRun.objects.filter(
        pk=detector_run.pk,
        lease_owner_id=detector_run.lease_owner_id,
        status=DetectorRun.Status.RUNNING,
    ).update(heartbeat_at=now, leased_until=now + dt.timedelta(seconds=LEASE_SECONDS))
    if updated != 1:
        raise NotLeaseOwner("This worker no longer holds the lease.")


def _next_case_number(organization_id: uuid.UUID) -> str:
    count = ExceptionCase.objects.filter(organization_id=organization_id).count()
    return f"REV-{count + 1:05d}"


def _upsert_case(detector_run: DetectorRun, result: DetectionResult) -> tuple[ExceptionCase, bool]:
    """Create the case for a match, or refresh the existing open case with this fingerprint."""
    organization = detector_run.organization
    fingerprint = result.fingerprint
    work_order_id = uuid.UUID(result.subject_id)

    # Condition 8: one case per tenant / work order / service occurrence, across every
    # rule version and every state. The occurrence is the identity; the fingerprint is
    # the creation-time evidence hash and is kept for audit.
    existing = (
        ExceptionCase.objects.select_for_update()
        .filter(
            organization=organization,
            exception_type=ExceptionType.REVENUE_COMPLETED_UNBILLED,
            work_order_id=work_order_id,
            service_date=result.service_date,
        )
        .first()
    ) or (
        ExceptionCase.objects.select_for_update()
        .filter(organization=organization, fingerprint=fingerprint)
        .first()
    )

    if existing is not None:
        if existing.is_terminal:
            # A resolved or dismissed case for this occurrence stands. Never reopen.
            return existing, False
        # Refresh evidence on the open case; never touch its state.
        existing.severity = result.severity
        existing.deadline_at = result.deadline_at
        existing.source_freshness_status = result.freshness_status
        existing.rule_explanation = result.explanation
        existing.rule_version = result.rule_version
        existing.recommended_next_action = result.recommended_next_action
        existing.recommended_next_action_explanation = result.recommended_next_action_explanation
        existing.last_refreshed_by_run = detector_run
        existing.save()
        return existing, False

    for _ in range(5):  # case_number is derived from a count; retry on a rare race
        try:
            with transaction.atomic():
                case = ExceptionCase.objects.create(
                    organization=organization,
                    case_number=_next_case_number(organization.id),
                    fingerprint=fingerprint,
                    exception_type=ExceptionType.REVENUE_COMPLETED_UNBILLED,
                    state=CaseState.NEW,
                    severity=result.severity,
                    detected_at=detector_run.as_of,
                    deadline_at=result.deadline_at,
                    work_order_id=work_order_id,
                    service_date=result.service_date,
                    detector_code=result.rule_code,
                    rule_version=result.rule_version,
                    rule_explanation=result.explanation,
                    source_freshness_status=result.freshness_status,
                    recommended_next_action=result.recommended_next_action,
                    recommended_next_action_explanation=result.recommended_next_action_explanation,
                    detector_run=detector_run,
                    last_refreshed_by_run=detector_run,
                )
                break
        except IntegrityError:
            continue
    else:  # pragma: no cover
        raise RuntimeError("Could not allocate a unique case number.")

    ExceptionEvent.objects.create(
        organization=organization,
        exception_case=case,
        event_type="detected",
        to_state=CaseState.NEW,
        actor_kind=ExceptionEvent.ActorKind.DETECTOR,
        actor_rule=f"{result.rule_code}:v{result.rule_version}",
        reason_code=result.explanation_code,
        case_version=case.version,
        metadata={
            "detector_code": result.rule_code,
            "rule_version": result.rule_version,
            "run_key": detector_run.reconciliation_run.run_key,
        },
    )
    audit.record(
        organization=organization,
        action="case.detected",
        object_type="exceptions.ExceptionCase",
        object_id=case.id,
        actor_rule=f"{result.rule_code}:v{result.rule_version}",
        metadata={
            "detector_code": result.rule_code,
            "rule_version": result.rule_version,
            "case_number": case.case_number,
        },
    )
    return case, True


def _link_sources(case: ExceptionCase, result: DetectionResult) -> None:
    for version_id in result.source_version_ids:
        version = SourceRecordVersion.objects.filter(
            organization=case.organization, id=version_id
        ).first()
        if version is None:
            continue
        ExceptionSourceLink.objects.get_or_create(
            organization=case.organization,
            exception_case=case,
            source_record_version=version,
            relationship=ExceptionSourceLink.Relationship.TRIGGER,
        )


@transaction.atomic
def persist(detector_run: DetectorRun, output: DetectorOutput) -> DetectorRun:
    """Write cases, snapshots, links, and the run outcome in one transaction.

    Raises NotLeaseOwner if the lease was lost, so a stale worker cannot commit.
    """
    locked = DetectorRun.objects.select_for_update().get(pk=detector_run.pk)
    if locked.lease_owner_id != detector_run.lease_owner_id or locked.is_terminal:
        raise NotLeaseOwner("Lease lost or run already finished; refusing to persist.")

    created = updated = 0
    for result in output.matches:
        case, is_new = _upsert_case(locked, result)
        if is_new:
            created += 1
        else:
            updated += 1
        _link_sources(case, result)
        if result.financial is not None:
            financial.record_candidate(
                case=case,
                financial=result.financial,
                calculation_code=revenue_unbilled.CALCULATION_CODE,
                calculation_version=revenue_unbilled.CALCULATION_VERSION,
                rule_identity=f"{output.rule_code}:v{output.rule_version}",
            )

    contradicted = _flag_cases_that_stopped_matching(locked, output)

    locked.status = DetectorRun.Status.SUCCEEDED
    locked.finished_at = timezone.now()
    locked.scanned_count = output.scanned
    locked.created_count = created
    locked.updated_count = updated + contradicted
    locked.skipped_count = sum(output.skip_reasons.values())
    locked.skip_reasons = output.skip_reasons
    locked.source_freshness = output.freshness
    locked.save()
    return locked


def _flag_cases_that_stopped_matching(detector_run: DetectorRun, output: DetectorOutput) -> int:
    """Section 23.1 line 1401: a later accounting fact for an open case "flags the open
    case for finance review; it does NOT change ExceptionCase.state."

    For every OPEN revenue case in this organization whose work order was evaluated on
    this run and did NOT match, append a `contradicted` timeline event carrying the
    skip reason, link any live invoice as contradicting evidence, and point the
    recommended next action at finance review. The state is never touched; a finance
    reviewer or owner resolves or dismisses it through the transition service.
    """
    from apps.operations.models import AccountingInvoice

    matched_ids = {r.subject_id for r in output.matches}
    reasons = {r.subject_id: r.skip_reason for r in output.results if not r.matched}
    count = 0
    open_cases = ExceptionCase.objects.select_for_update().filter(
        organization=detector_run.organization,
        exception_type=ExceptionType.REVENUE_COMPLETED_UNBILLED,
        state__in=[s for s in CaseState.values if s not in ("resolved", "dismissed")],
    )
    for case in open_cases:
        subject = str(case.work_order_id)
        if subject in matched_ids or subject not in reasons:
            continue
        reason = reasons[subject]
        if (
            case.recommended_next_action == "finance_review_contradiction"
            and case.last_refreshed_by_run_id == detector_run.id
        ):
            continue
        case.recommended_next_action = "finance_review_contradiction"
        case.recommended_next_action_explanation = (
            f"On re-evaluation this work order no longer meets the rule ({reason}). "
            "Finance should resolve with source_corrected or dismiss with the matching code."
        )
        case.source_freshness_status = _overall(output.freshness)
        case.last_refreshed_by_run = detector_run
        case.save()
        ExceptionEvent.objects.create(
            organization=case.organization,
            exception_case=case,
            event_type="contradicted",
            actor_kind=ExceptionEvent.ActorKind.DETECTOR,
            actor_rule=f"{output.rule_code}:v{output.rule_version}",
            reason_code=reason[:40],
            case_version=case.version,
            metadata={"skip_reason": reason, "run_key": detector_run.reconciliation_run.run_key},
        )
        if reason == "invoice_present" and case.work_order:
            wo = case.work_order
            for invoice in AccountingInvoice.objects.filter(
                organization=case.organization, customer_id=wo.customer_id, site_id=wo.site_id
            ).exclude(source_status=AccountingInvoice.SourceStatus.VOID):
                for version in SourceRecordVersion.objects.filter(
                    organization=case.organization,
                    record_type="accounting_invoice",
                ).filter(
                    external_id__in=invoice.external_references.values_list(
                        "external_id", flat=True
                    )
                )[:1]:
                    ExceptionSourceLink.objects.get_or_create(
                        organization=case.organization,
                        exception_case=case,
                        source_record_version=version,
                        relationship=ExceptionSourceLink.Relationship.CONTRADICTING,
                    )
        count += 1
    return count


def _overall(freshness: dict[str, str]) -> str:
    values = set(freshness.values())
    for level in ("stale", "aging", "unknown"):
        if level in values:
            return level
    return "fresh"


@transaction.atomic
def fail(detector_run: DetectorRun, *, code: str, summary: str) -> DetectorRun:
    locked = DetectorRun.objects.select_for_update().get(pk=detector_run.pk)
    if locked.lease_owner_id != detector_run.lease_owner_id:
        raise NotLeaseOwner("Lease lost; refusing to mark failed.")
    locked.status = DetectorRun.Status.FAILED
    locked.finished_at = timezone.now()
    locked.failure_code = code[:64]
    locked.failure_summary = summary[:500]
    locked.save()
    return locked


def evaluate_and_persist(
    *, run: ReconciliationRun, detector_code: str, as_of: dt.datetime | None = None
) -> DetectorRun | None:
    """Claim, evaluate, persist. The whole idempotent unit a task or command invokes.

    Returns None when another worker holds the lease (nothing to do), otherwise the
    finished DetectorRun. Duplicate invocations against the same manifest converge on
    the same DetectorRun row and the same cases.
    """
    module = DETECTORS[detector_code]
    moment = as_of or timezone.now()
    detector_run = claim(
        run=run, detector_code=detector_code, rule_version=module.RULE_VERSION, as_of=moment
    )
    if detector_run is None:
        return None
    if detector_run.status == DetectorRun.Status.SUCCEEDED:
        return detector_run  # already evaluated; at-least-once delivery made this a no-op
    try:
        output = module.evaluate(run, as_of=moment)
        return persist(detector_run, output)
    except NotLeaseOwner:
        raise
    except Exception as exc:  # noqa: BLE001 - recorded, never swallowed silently
        fail(detector_run, code=type(exc).__name__, summary="Detector evaluation raised.")
        raise
