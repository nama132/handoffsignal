"""Read paths for cases. Every function takes an explicit organization."""

from __future__ import annotations

import uuid

from django.db.models import Case, IntegerField, QuerySet, Value, When

from apps.exceptions.models import CaseState, DetectorRun, ExceptionCase, Severity

_SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}
OPEN_STATES = [s for s in CaseState.values if s not in ("resolved", "dismissed")]


def cases_for_organization(
    organization_id: uuid.UUID,
    *,
    limit_to_site_ids: set[uuid.UUID] | None = None,
    state: str = "",
    severity: str = "",
    owner_id: uuid.UUID | None = None,
) -> QuerySet[ExceptionCase]:
    """Inbox query. Default sort per section 30.2: overdue/critical, nearest deadline, detection."""
    queryset = ExceptionCase.objects.filter(organization_id=organization_id).select_related(
        "work_order", "work_order__site", "work_order__customer", "owner_membership__user"
    )
    if limit_to_site_ids is not None:
        queryset = queryset.filter(work_order__site_id__in=limit_to_site_ids)
    if state:
        queryset = queryset.filter(state=state)
    if severity:
        queryset = queryset.filter(severity=severity)
    if owner_id is not None:
        queryset = queryset.filter(owner_membership_id=owner_id)

    severity_rank = Case(
        *[When(severity=k, then=Value(v)) for k, v in _SEVERITY_RANK.items()],
        default=Value(9),
        output_field=IntegerField(),
    )
    return queryset.annotate(_sev=severity_rank).order_by("_sev", "deadline_at", "-detected_at")


def get_case_or_none(
    organization_id: uuid.UUID,
    case_id: uuid.UUID,
    *,
    limit_to_site_ids: set[uuid.UUID] | None = None,
) -> ExceptionCase | None:
    queryset = ExceptionCase.objects.filter(organization_id=organization_id, id=case_id)
    if limit_to_site_ids is not None:
        queryset = queryset.filter(work_order__site_id__in=limit_to_site_ids)
    return queryset.select_related(
        "work_order", "work_order__site", "work_order__customer", "work_order__contract"
    ).first()


def open_case_counts(
    organization_id: uuid.UUID, *, limit_to_site_ids: set[uuid.UUID] | None = None
) -> dict[str, int]:
    """Open-case counts by severity, honouring the caller's site scope.

    `limit_to_site_ids` is the same three-valued contract `cases_for_organization` uses:
    `None` means tenant-wide, a set means exactly those sites, and the **empty set means
    no sites at all**. The empty set must reach `filter(id__in=set())` verbatim so it
    yields nothing -- collapsing it to "no filter" is precisely the leak this parameter
    exists to close.
    """
    from django.db.models import Count

    queryset = ExceptionCase.objects.filter(organization_id=organization_id, state__in=OPEN_STATES)
    if limit_to_site_ids is not None:
        queryset = queryset.filter(work_order__site_id__in=limit_to_site_ids)
    rows = queryset.values("severity").annotate(n=Count("id"))
    counts = dict.fromkeys(Severity.values, 0)
    for row in rows:
        counts[row["severity"]] = row["n"]
    return counts


def recent_runs(organization_id: uuid.UUID, *, limit: int = 10) -> QuerySet[DetectorRun]:
    return DetectorRun.objects.filter(organization_id=organization_id).select_related(
        "reconciliation_run"
    )[:limit]


def failed_runs(organization_id: uuid.UUID) -> QuerySet[DetectorRun]:
    return DetectorRun.objects.filter(
        organization_id=organization_id, status=DetectorRun.Status.FAILED
    )
