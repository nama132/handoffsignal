"""REVENUE_COMPLETED_UNBILLED_V1 (master prompt section 24.2).

The one detector Route B builds. It flags a work order only when **all eight** conditions
hold. The order below is deliberate: cheap, positive-fact checks run first; the
negative-evidence check (condition 4) runs last and only after coverage is proven, so an
"absence" can never be asserted from missing data.

Section 24 preamble: "No detector may turn a missing row into a negative fact unless its
ReconciliationRun manifest contains a fresh, committed, authoritative, `complete`
snapshot coverage row for the exact entity scope and entire decision interval."
"""

from __future__ import annotations

import datetime as dt
import zoneinfo
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from apps.exceptions.detectors.base import (
    DetectionResult,
    DetectorOutput,
    FinancialInputs,
    SkipReason,
)
from apps.exceptions.models import Severity
from apps.ingestion.models import (
    ExternalEntityReference,
    IdentityResolutionIssue,
    ImportCoverage,
    ReconciliationIssue,
    ReconciliationRun,
    SourceRecordVersion,
)
from apps.operations.models import AccountingInvoice, ServiceObligation, WorkOrder

RULE_CODE = "REVENUE_COMPLETED_UNBILLED_V1"
RULE_VERSION = 1
CALCULATION_CODE = "CANDIDATE_VALUE_V1"
CALCULATION_VERSION = 1

#: The one coverage contract this detector accepts for the accounting search. A
#: declaration under any other contract or version cannot prove absence (line 396).
ACCOUNTING_CONTRACT = ImportCoverage.QueryContract.ACCOUNTING_SERVICE_DATE_LEDGER_V1
ACCOUNTING_CONTRACT_VERSION = 1
OPERATIONS_CONTRACT = ImportCoverage.QueryContract.SERVICE_EVENT_CURRENT_STATE_V1

# Section 24.2 defines no deadline or severity rule (24.1 and 24.3 do). These are LOCAL
# decisions recorded in ADR 0007, not specification requirements. They are versioned so
# a later change is a new rule, not a silent edit.
DEADLINE_RULE = "REVENUE_DEADLINE_V1"
DEADLINE_GRACE_DAYS = 30
SEVERITY_RULE = "REVENUE_SEVERITY_V1"


def _site_local_date(instant: dt.datetime, tz_name: str) -> dt.date:
    """Convert an instant to the site's calendar date.

    Section 22.3 line 893: the accounting ledger contract is keyed on service_date "in
    the site-local calendar dates represented by the half-open interval". Using UTC here
    would shift evening completions across midnight and miss or mis-match invoices.
    """
    return instant.astimezone(zoneinfo.ZoneInfo(tz_name)).date()


def _freshness(run_input, as_of: dt.datetime) -> str:
    """Freshness of the batch ON THE MANIFEST, judged against the source's policy.

    The observation time comes from the immutable ImportBatch the run selected, never
    from the mutable DataSource row: a later import must not retroactively change what
    this evaluation saw (section 16.2, "as of its declared time/watermarks").
    """
    if run_input is None or run_input.import_batch is None:
        return "unknown"
    batch = run_input.import_batch
    maximum = batch.source.maximum_age_minutes
    if maximum is None:
        return "unknown"
    age = (as_of - batch.source_as_of_at).total_seconds() / 60
    if age > maximum:
        return "stale"
    if age > maximum * 0.75:
        return "aging"
    return "fresh"


class NoServiceDate(ValueError):
    """A work order carries no date at all, so no occurrence can be identified."""


def _service_dates(work_order: WorkOrder) -> tuple[dt.date, frozenset[dt.date]]:
    """The occurrence's primary service date, and every date an invoice might carry.

    Service windows cross midnight (the fixtures run 18:00-02:00), so a job started on
    day D and finished at 01:30 on D+1 is a D occurrence to the customer and to the
    accounting ledger, whose `service_date` is a plain date the source chose. Searching
    on the completion date alone would miss a D invoice and raise a FALSE POSITIVE.

    Primary = site-local date of `scheduled_at` when present, else of `completed_at`.
    Candidates = primary plus the site-local completion date. Both are searched and
    both must be inside the declared coverage interval.

    The detector only reaches this after condition 2, so a completion time is normally
    present. The evidence checklist calls it for every ledger row, including work that
    has not been completed, so an incomplete work order must return its scheduled date
    rather than raise -- the checklist reports the missing completion as its own item.
    Raising `NoServiceDate` is reserved for a work order with neither timestamp, which
    the model's own constraints already prevent.
    """
    tz = work_order.site.timezone
    completed = (
        _site_local_date(work_order.completed_at, tz)
        if work_order.completed_at is not None
        else None
    )
    scheduled = (
        _site_local_date(work_order.scheduled_at, tz)
        if work_order.scheduled_at is not None
        else None
    )
    primary = scheduled or completed
    if primary is None:
        raise NoServiceDate(
            f"Work order {work_order.pk} has neither a scheduled nor a completion time."
        )
    candidates = {primary} | ({completed} if completed is not None else set())
    return primary, frozenset(candidates)


def _authorization_required(work_order: WorkOrder, obligation: ServiceObligation) -> bool:
    """Authorization is required if the work order OR the obligation's policy says so.

    A work-order flag alone can be wrong at source; the contract's declared policy
    for authorized extra work is an independent check (condition 5 read together with
    ServiceObligation.extra_work_requires_authorization).
    """
    policy_requires = (
        obligation.extra_work_requires_authorization
        and obligation.scope_kind == ServiceObligation.ScopeKind.AUTHORIZED_EXTRA
    )
    return bool(work_order.authorization_required or policy_requires)


def _has_authorization(work_order: WorkOrder, obligation: ServiceObligation) -> bool:
    if not _authorization_required(work_order, obligation):
        return True
    return bool(work_order.authorization_reference) and work_order.authorized_at is not None


def _accounting_coverage_proves_absence(
    run: ReconciliationRun, work_order: WorkOrder, service_dates: frozenset[dt.date]
) -> bool:
    """Condition 4's precondition: may we claim "no invoice" at all?

    Requires an ImportCoverage row on the run manifest that:
      * proves_absence (complete + authoritative + committed + snapshot),
      * declares the exact accounting contract and version,
      * is scoped to the organization, this customer, or this site,
      * and whose half-open interval contains the service date.
    """
    run_input = run.inputs.filter(domain="invoice_status").first()
    if run_input is None:
        return False

    for cov in run_input.coverage_declarations.all():
        if not cov.proves_absence:
            continue
        if (
            cov.query_contract_code != ACCOUNTING_CONTRACT
            or cov.query_contract_version != ACCOUNTING_CONTRACT_VERSION
        ):
            continue
        in_scope = (
            cov.scope_type == ImportCoverage.ScopeType.ORGANIZATION
            or cov.scope_type == ImportCoverage.ScopeType.SOURCE_LEDGER
            or (
                cov.scope_type == ImportCoverage.ScopeType.CUSTOMER
                and cov.customer_id == work_order.customer_id
            )
            or (
                cov.scope_type == ImportCoverage.ScopeType.SITE
                and cov.site_id == work_order.site_id
            )
        )
        if not in_scope:
            continue
        # A batch that still holds quarantined rows is not a complete observation of
        # its own file: something in it was never imported. It cannot prove absence
        # until those rows are re-resolved and promoted.
        if cov.import_batch.rows.filter(status="invalid").exists():
            continue
        # Half-open [start, end): convert the instants to site-local dates. EVERY
        # candidate service date must fall inside the interval.
        tz = work_order.site.timezone
        start_date = _site_local_date(cov.coverage_start_at, tz)
        end_date = _site_local_date(cov.coverage_end_at, tz)
        if all(start_date <= d < end_date for d in service_dates):
            return True
    return False


def _confirmed_invoice_exists(work_order: WorkOrder, service_dates: frozenset[dt.date]) -> bool:
    """Condition 4: a confirmed, non-void invoice mapped to this work order OR matching
    customer + site + ANY candidate service date. Void invoices do not count as billing.
    Searching every candidate date is deliberately conservative: a missed invoice is a
    false positive, which section 8.3 names as a kill criterion."""
    live = AccountingInvoice.objects.filter(organization_id=work_order.organization_id).exclude(
        source_status=AccountingInvoice.SourceStatus.VOID
    )
    if live.filter(work_order_id=work_order.id).exists():
        return True
    return live.filter(
        customer_id=work_order.customer_id,
        site_id=work_order.site_id,
        service_date__in=list(service_dates),
    ).exists()


def _candidate_value(
    work_order: WorkOrder, obligation: ServiceObligation | None
) -> FinancialInputs:
    """Section 24.2 candidate-value rules. Unknown is NULL, never zero.

    The work order's own billing basis wins when present; otherwise the obligation's.
    All arithmetic is Decimal at four places; display quantizes to cents later.
    """
    basis = work_order.billing_basis or (obligation.billing_basis if obligation else "")
    assumptions: dict[str, object] = {
        "work_order_id": str(work_order.id),
        "basis_source": "work_order" if work_order.billing_basis else "service_obligation",
    }

    if basis == ServiceObligation.BillingBasis.FIXED_WORK_ORDER:
        if work_order.approved_fixed_amount is None:
            return FinancialInputs(
                "manual_amount_required", None, {**assumptions, "missing": "approved_fixed_amount"}
            )
        assumptions["approved_fixed_amount"] = str(work_order.approved_fixed_amount)
        return FinancialInputs("fixed_work_order", work_order.approved_fixed_amount, assumptions)

    if basis == ServiceObligation.BillingBasis.HOURLY_ACTUAL:
        rate = work_order.bill_rate or (obligation.default_bill_rate if obligation else None)
        if work_order.approved_hours is None or rate is None:
            return FinancialInputs(
                "manual_amount_required",
                None,
                {
                    **assumptions,
                    "missing": "approved_hours"
                    if work_order.approved_hours is None
                    else "bill_rate",
                },
            )
        value = (work_order.approved_hours * rate).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        assumptions.update(
            {
                "approved_hours": str(work_order.approved_hours),
                "bill_rate": str(rate),
                "rate_source": "work_order" if work_order.bill_rate else "service_obligation",
            }
        )
        return FinancialInputs("hourly_actual", value, assumptions)

    if basis == ServiceObligation.BillingBasis.HOURLY_SCHEDULED:
        # Section 24.2: "use scheduled hours only when the contract explicitly uses that
        # basis". Route B imports no scheduled hours, so this always needs a human.
        return FinancialInputs(
            "manual_amount_required", None, {**assumptions, "missing": "scheduled_hours"}
        )

    return FinancialInputs(
        "manual_amount_required", None, {**assumptions, "missing": "billing_basis"}
    )


def _severity(candidate: Decimal | None, days_overdue: int) -> str:
    """REVENUE_SEVERITY_V1 — a local, versioned rule (ADR 0007), not a spec requirement."""
    if days_overdue >= 60:
        return Severity.HIGH
    if days_overdue >= 30 or (candidate is not None and candidate >= Decimal("1000")):
        return Severity.MEDIUM
    return Severity.LOW


def evaluate(run: ReconciliationRun, *, as_of: dt.datetime | None = None) -> DetectorOutput:
    """Evaluate every work order in the run's organization. Pure with respect to writes."""
    moment = as_of or timezone.now()
    output = DetectorOutput(rule_code=RULE_CODE, rule_version=RULE_VERSION, as_of=moment)
    organization_id = run.organization_id

    # Source freshness for the two feeds the decision depends on.
    ops_input = (
        run.inputs.filter(domain="service_events").select_related("import_batch__source").first()
    )
    acct_input = (
        run.inputs.filter(domain="invoice_status").select_related("import_batch__source").first()
    )
    ops_fresh = _freshness(ops_input, moment)
    acct_fresh = _freshness(acct_input, moment)
    output.freshness = {"service_events": ops_fresh, "invoice_status": acct_fresh}

    # A blocking reconciliation issue or an unresolved identity halts every claim.
    blocked = (
        ReconciliationIssue.objects.filter(
            organization_id=organization_id,
            status=ReconciliationIssue.Status.OPEN,
            is_blocking=True,
        ).exists()
        or IdentityResolutionIssue.objects.filter(
            organization_id=organization_id, status=IdentityResolutionIssue.Status.UNRESOLVED
        ).exists()
    )

    work_orders = (
        WorkOrder.objects.filter(organization_id=organization_id)
        .select_related("site", "contract", "service_obligation", "customer")
        .order_by("completed_at", "id")
    )

    for work_order in work_orders:
        output.scanned += 1
        subject = str(work_order.id)

        def skip(reason: str, subject_id: str = subject) -> DetectionResult:
            return DetectionResult(False, RULE_CODE, RULE_VERSION, subject_id, skip_reason=reason)

        if blocked:
            output.results.append(skip(SkipReason.BLOCKING_RECONCILIATION_ISSUE))
            continue

        # 1. billable with confirmed canonical mappings
        if not work_order.billable:
            output.results.append(skip(SkipReason.NOT_BILLABLE))
            continue
        has_mapping = ExternalEntityReference.objects.filter(
            organization_id=organization_id,
            entity_type="work_order",
            work_order=work_order,
            mapping_status=ExternalEntityReference.MappingStatus.CONFIRMED,
        ).exists()
        if not has_mapping:
            output.results.append(skip(SkipReason.IDENTITY_UNRESOLVED))
            continue

        # 2. completed with a completion instant
        if work_order.status != WorkOrder.Status.COMPLETED or work_order.completed_at is None:
            output.results.append(skip(SkipReason.NOT_COMPLETED))
            continue

        # 3. obligation supports the basis and the configured delay has elapsed
        obligation = work_order.service_obligation
        if obligation is None:
            output.results.append(skip(SkipReason.NO_SERVICE_OBLIGATION))
            continue
        delay_elapsed_at = work_order.completed_at + dt.timedelta(
            days=obligation.uninvoiced_delay_days
        )
        if moment < delay_elapsed_at:
            output.results.append(skip(SkipReason.DELAY_NOT_ELAPSED))
            continue

        # 5. authorization evidenced when required (work-order flag OR contract policy)
        if not _has_authorization(work_order, obligation):
            output.results.append(skip(SkipReason.AUTHORIZATION_MISSING))
            continue

        # 6. contract active for the service date, basis supported
        service_date, service_dates = _service_dates(work_order)
        if not work_order.contract.is_active_on(service_date):
            output.results.append(skip(SkipReason.CONTRACT_NOT_ACTIVE))
            continue
        financial = _candidate_value(work_order, obligation)
        basis_declared = work_order.billing_basis or obligation.billing_basis
        if basis_declared == ServiceObligation.BillingBasis.INCLUDED:
            # Included in the base contract: nothing separate is owed.
            output.results.append(skip(SkipReason.BILLING_BASIS_UNSUPPORTED))
            continue

        # freshness: stale operations or accounting data cannot support a claim
        if ops_fresh == "stale":
            output.results.append(skip(SkipReason.OPERATIONS_STALE))
            continue
        if acct_fresh == "stale":
            output.results.append(skip(SkipReason.ACCOUNTING_STALE))
            continue

        # 4. the negative claim, gated on proven coverage
        if not _accounting_coverage_proves_absence(run, work_order, service_dates):
            output.results.append(skip(SkipReason.INSUFFICIENT_COVERAGE))
            continue
        if _confirmed_invoice_exists(work_order, service_dates):
            output.results.append(skip(SkipReason.INVOICE_PRESENT))
            continue

        # ---- matched ----
        days_overdue = (moment - delay_elapsed_at).days
        deadline = delay_elapsed_at + dt.timedelta(days=DEADLINE_GRACE_DAYS)
        freshness_status = (
            "stale"
            if "stale" in (ops_fresh, acct_fresh)
            else (
                "aging"
                if "aging" in (ops_fresh, acct_fresh)
                else ("unknown" if "unknown" in (ops_fresh, acct_fresh) else "fresh")
            )
        )

        source_versions = list(
            SourceRecordVersion.objects.filter(
                organization_id=organization_id,
                record_type="work_order",
            )
            .filter(
                external_id__in=ExternalEntityReference.objects.filter(
                    organization_id=organization_id,
                    work_order=work_order,
                    entity_type="work_order",
                ).values_list("external_id", flat=True)
            )
            .order_by("-imported_at")
            .values_list("id", flat=True)[:1]
        )

        output.results.append(
            DetectionResult(
                matched=True,
                rule_code=RULE_CODE,
                rule_version=RULE_VERSION,
                subject_id=subject,
                service_date=service_date,
                fingerprint_inputs={
                    "organization": str(organization_id),
                    "rule": RULE_CODE,
                    "rule_version": str(RULE_VERSION),
                    "work_order": subject,
                    "service_date": service_date.isoformat(),
                },
                source_version_ids=[str(v) for v in source_versions],
                freshness_status=freshness_status,
                severity=_severity(financial.candidate_value, days_overdue),
                deadline_at=deadline,
                explanation_code="completed_unbilled",
                explanation=(
                    f"Work order completed on {service_date.isoformat()} (site-local), billable, "
                    f"authorized where required, contract active; {obligation.uninvoiced_delay_days}-day "
                    f"uninvoiced delay elapsed on {delay_elapsed_at.date().isoformat()}; the accounting "
                    f"snapshot declared complete coverage of this customer/site for that date and "
                    f"contains no posted invoice matching it."
                ),
                recommended_next_action="finance_review_candidate",
                recommended_next_action_explanation=(
                    "A finance reviewer should validate completion, authorization, rate basis, and "
                    "duplicate-invoice status before this becomes invoice-ready."
                ),
                financial=financial,
            )
        )

    return output
