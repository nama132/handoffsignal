"""Detection and exception records (master prompt sections 22.3 and 22.5).

Route B scope: one exception type, `revenue_completed_unbilled`. The `ExceptionType`
vocabulary carries all three values so the model stays faithful to the specification,
but no attendance or quality detector exists and no placeholder for one is created.

Three invariants are structural rather than conventional:

* `ExceptionCase.state` can only change through `services.transitions`. `save()` refuses
  a state change that did not pass through that service.
* `ExceptionEvent` rows are append-only: `save()` refuses updates, `delete()` refuses.
* `DetectorRun` uniqueness is on the immutable evaluation identity, not on the schedule
  window, so a corrected manifest in the same window gets its own evaluation (line 713).
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.common.models import (
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
    TenantScopedModel,
    VersionedModel,
)
from apps.common.validators import assert_same_organization


class AppendOnlyError(RuntimeError):
    pass


class DirectStateChangeError(RuntimeError):
    """Raised when ExceptionCase.state is changed outside the transition service."""


# ------------------------------------------------------------------ dispatch and runs


class DetectorDispatchIntent(TenantScopedModel):
    """A durable promise to evaluate one detector against one immutable manifest.

    Section 22.3: created "in the same database transaction that makes a
    detector-enabled reconciliation run ready". Publication to the broker is
    at-least-once; the unique DetectorRun key makes duplicate deliveries harmless.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PUBLISHING = "publishing", "Publishing"
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"

    reconciliation_run = models.ForeignKey(
        "ingestion.ReconciliationRun", on_delete=models.PROTECT, related_name="dispatch_intents"
    )
    detector_code = models.CharField(max_length=64)
    rule_version = models.PositiveIntegerField()
    input_manifest_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    claim_owner_id = models.CharField(max_length=128, blank=True)
    leased_until = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    broker_task_id = models.CharField(max_length=128, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "exceptions_detector_dispatch_intent"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "reconciliation_run",
                    "detector_code",
                    "rule_version",
                    "input_manifest_sha256",
                ],
                name="uniq_dispatch_intent_evaluation",
            )
        ]
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.detector_code}@{self.input_manifest_sha256[:8]} ({self.status})"

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "reconciliation_run")


class DetectorRun(TenantScopedModel):
    """One evaluation of one detector against one immutable manifest.

    Section 22.5: unique on `(organization, reconciliation_run, detector_code,
    rule_version, input_manifest_sha256)`. Claimed with an atomic state/expiry predicate;
    only the current owner may heartbeat or finish; a new worker may reclaim only after
    `leased_until`, incrementing `attempt_count`.
    """

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        PARTIAL = "partial", "Partial"

    reconciliation_run = models.ForeignKey(
        "ingestion.ReconciliationRun", on_delete=models.PROTECT, related_name="detector_runs"
    )
    detector_code = models.CharField(max_length=64)
    rule_version = models.PositiveIntegerField()
    as_of = models.DateTimeField()
    input_manifest_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status, default=Status.RUNNING)

    lease_owner_id = models.CharField(max_length=128, blank=True)
    leased_until = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=1)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    source_freshness = models.JSONField(default=dict, blank=True)
    scanned_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    skip_reasons = models.JSONField(
        default=dict, blank=True, help_text="Reason code -> count. The visible skipped count."
    )
    failure_code = models.CharField(max_length=64, blank=True)
    failure_summary = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "exceptions_detector_run"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "organization",
                    "reconciliation_run",
                    "detector_code",
                    "rule_version",
                    "input_manifest_sha256",
                ],
                name="uniq_detector_run_evaluation",
            ),
            models.CheckConstraint(
                condition=~Q(status__in=["succeeded", "failed", "partial"])
                | Q(finished_at__isnull=False),
                name="ck_detector_run_finished_has_timestamp",
            ),
        ]
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.detector_code} v{self.rule_version} ({self.status})"

    @property
    def is_terminal(self) -> bool:
        return self.status != self.Status.RUNNING

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "reconciliation_run")


class DetectorScheduleLease(TenantScopedModel):
    """Prevents two schedulers from selecting the same cadence window.

    Section 22.5: "This prevents duplicate cadence scheduling only. It never overwrites
    or substitutes for DetectorRun evaluation uniqueness."
    """

    detector_code = models.CharField(max_length=64)
    rule_version = models.PositiveIntegerField()
    run_window_start = models.DateTimeField()
    run_window_end = models.DateTimeField()
    lease_owner_id = models.CharField(max_length=128, blank=True)
    leased_until = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    reconciliation_run = models.ForeignKey(
        "ingestion.ReconciliationRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="schedule_leases",
    )

    class Meta:
        db_table = "exceptions_detector_schedule_lease"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "organization",
                    "detector_code",
                    "rule_version",
                    "run_window_start",
                    "run_window_end",
                ],
                name="uniq_schedule_lease_window",
            ),
            models.CheckConstraint(
                condition=Q(run_window_end__gt=models.F("run_window_start")),
                name="ck_schedule_lease_window_ordered",
            ),
        ]
        ordering = ["-run_window_start"]

    def __str__(self) -> str:
        return f"{self.detector_code} {self.run_window_start:%Y-%m-%d %H:%M}"


# ------------------------------------------------------------------ exception cases


class ExceptionType(models.TextChoices):
    ATTENDANCE_NO_CHECK_IN = "attendance_no_check_in", "Attendance: no check-in"
    REVENUE_COMPLETED_UNBILLED = "revenue_completed_unbilled", "Revenue: completed but unbilled"
    QUALITY_CORRECTION_DUE = "quality_correction_due", "Quality: correction due"


#: The only exception type Route B builds. A detector for any other type does not exist.
ROUTE_B_EXCEPTION_TYPES: frozenset[str] = frozenset({ExceptionType.REVENUE_COMPLETED_UNBILLED})


class CaseState(models.TextChoices):
    NEW = "new", "New"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    ACTION_PENDING = "action_pending", "Action pending"
    WAITING_EXTERNAL = "waiting_external", "Waiting on external"
    ESCALATED = "escalated", "Escalated"
    RESOLVED = "resolved", "Resolved"
    DISMISSED = "dismissed", "Dismissed"


TERMINAL_STATES: frozenset[str] = frozenset({CaseState.RESOLVED, CaseState.DISMISSED})


class Severity(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class FreshnessStatus(models.TextChoices):
    FRESH = "fresh", "Fresh"
    AGING = "aging", "Aging"
    STALE = "stale", "Stale"
    UNKNOWN = "unknown", "Unknown"


class ResolutionCode(models.TextChoices):
    REPLACEMENT_CONFIRMED = "replacement_confirmed", "Replacement confirmed"
    SUPERVISOR_COVERED = "supervisor_covered", "Supervisor covered"
    SERVICE_RESCHEDULED = "service_rescheduled", "Service rescheduled"
    SOURCE_CORRECTED = "source_corrected", "Source corrected"
    INVOICE_HANDOFF_PREPARED = "invoice_handoff_prepared", "Invoice handoff prepared"
    DEFICIENCY_CORRECTED = "deficiency_corrected", "Deficiency corrected"
    CLIENT_CANCELLED = "client_cancelled", "Client cancelled"
    ACCEPTED_UNCOVERED = "accepted_uncovered", "Accepted uncovered"


class DismissalCode(models.TextChoices):
    FALSE_POSITIVE = "false_positive", "False positive"
    DUPLICATE_SOURCE_RECORD = "duplicate_source_record", "Duplicate source record"
    SOURCE_STALE = "source_stale", "Source stale"
    NOT_BILLABLE = "not_billable", "Not billable"
    ALREADY_INVOICED = "already_invoiced", "Already invoiced"
    CONTRACT_EXCLUDED = "contract_excluded", "Contract excluded"
    CANCELLED_AT_SOURCE = "cancelled_at_source", "Cancelled at source"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence", "Insufficient evidence"


#: Resolution codes that make sense for a revenue case (section 23, line 1352-1363).
REVENUE_RESOLUTION_CODES: frozenset[str] = frozenset(
    {
        ResolutionCode.SOURCE_CORRECTED,
        ResolutionCode.INVOICE_HANDOFF_PREPARED,
        ResolutionCode.CLIENT_CANCELLED,
    }
)
REVENUE_DISMISSAL_CODES: frozenset[str] = frozenset(
    {
        DismissalCode.FALSE_POSITIVE,
        DismissalCode.DUPLICATE_SOURCE_RECORD,
        DismissalCode.SOURCE_STALE,
        DismissalCode.NOT_BILLABLE,
        DismissalCode.ALREADY_INVOICED,
        DismissalCode.CONTRACT_EXCLUDED,
        DismissalCode.CANCELLED_AT_SOURCE,
        DismissalCode.INSUFFICIENT_EVIDENCE,
    }
)


class ExceptionCase(TenantScopedModel, VersionedModel):
    """One deduplicated exception. Section 22.5.

    `state` is guarded: the transition service sets a private flag before saving, and
    `save()` refuses a changed state without it. This is what makes "no view, admin,
    detector, or task sets state directly" (line 1319) testable rather than aspirational.
    """

    case_number = models.CharField(max_length=32)
    fingerprint = models.CharField(max_length=64)
    exception_type = models.CharField(max_length=40, choices=ExceptionType)
    state = models.CharField(max_length=24, choices=CaseState, default=CaseState.NEW)
    severity = models.CharField(max_length=16, choices=Severity)

    detected_at = models.DateTimeField()
    deadline_at = models.DateTimeField(null=True, blank=True)
    first_acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    owner_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="owned_cases",
    )

    # Exactly one primary domain object. Route B has only work orders; the other two
    # columns are absent because their models do not exist, so a case of another type
    # is structurally impossible in this phase.
    work_order = models.ForeignKey(
        "operations.WorkOrder",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="exception_cases",
    )

    # The service occurrence. Condition 8 (line 1437): no second case may represent the
    # same tenant, canonical work order and occurrence, across ANY rule version.
    service_date = models.DateField(null=True, blank=True)

    detector_code = models.CharField(max_length=64)
    rule_version = models.PositiveIntegerField()
    rule_explanation = models.TextField(
        help_text="Deterministic, from codes. Never free text from a model."
    )
    source_freshness_status = models.CharField(max_length=16, choices=FreshnessStatus)
    recommended_next_action = models.CharField(max_length=64)
    recommended_next_action_explanation = models.CharField(max_length=500)

    resolution_code = models.CharField(max_length=40, choices=ResolutionCode, blank=True)
    dismissal_code = models.CharField(max_length=40, choices=DismissalCode, blank=True)
    reason_text = models.CharField(max_length=1000, blank=True)

    detector_run = models.ForeignKey(
        DetectorRun,
        on_delete=models.PROTECT,
        related_name="cases",
        help_text="The run that created this case.",
    )
    last_refreshed_by_run = models.ForeignKey(
        DetectorRun, on_delete=models.PROTECT, null=True, blank=True, related_name="refreshed_cases"
    )

    class Meta:
        db_table = "exceptions_exception_case"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "case_number"], name="uniq_case_number_per_org"
            ),
            models.UniqueConstraint(
                fields=["organization", "fingerprint"], name="uniq_case_fingerprint_per_org"
            ),
            # One case per service occurrence, regardless of rule version or state
            # (condition 8, line 1437).
            models.UniqueConstraint(
                fields=["organization", "exception_type", "work_order", "service_date"],
                condition=Q(work_order__isnull=False) & Q(service_date__isnull=False),
                name="uniq_case_per_work_order_occurrence",
            ),
            # Route B: the only primary object is a work order, and a revenue case must have one.
            models.CheckConstraint(
                condition=~Q(exception_type="revenue_completed_unbilled")
                | Q(work_order__isnull=False),
                name="ck_revenue_case_has_work_order",
            ),
            models.CheckConstraint(
                condition=~Q(state="resolved")
                | (Q(resolved_at__isnull=False) & ~Q(resolution_code="")),
                name="ck_resolved_case_has_code_and_time",
            ),
            models.CheckConstraint(
                condition=~Q(state="dismissed") | ~Q(dismissal_code=""),
                name="ck_dismissed_case_has_code",
            ),
        ]
        ordering = ["-detected_at"]
        indexes = [
            models.Index(
                fields=["organization", "state", "severity"], name="idx_case_org_state_sev"
            ),
            models.Index(fields=["organization", "deadline_at"], name="idx_case_org_deadline"),
        ]

    def __str__(self) -> str:
        return self.case_number

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "owner_membership", "work_order", "detector_run")

    # ----- state guard -----------------------------------------------------------
    _state_change_authorized: bool = False

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            original = (
                ExceptionCase.objects.filter(pk=self.pk).values_list("state", flat=True).first()
            )
            if (
                original is not None
                and original != self.state
                and not self._state_change_authorized
            ):
                raise DirectStateChangeError(
                    "ExceptionCase.state may only change through services.transitions."
                )
        try:
            super().save(*args, **kwargs)
        finally:
            self._state_change_authorized = False


class ExceptionSourceLink(TenantScopedModel):
    """Which source versions support, trigger, contradict, or resolve a case."""

    class Relationship(models.TextChoices):
        TRIGGER = "trigger", "Trigger"
        SUPPORTING = "supporting", "Supporting"
        CONTRADICTING = "contradicting", "Contradicting"
        RESOLUTION = "resolution", "Resolution"

    exception_case = models.ForeignKey(
        ExceptionCase, on_delete=models.CASCADE, related_name="source_links"
    )
    source_record_version = models.ForeignKey(
        "ingestion.SourceRecordVersion", on_delete=models.PROTECT, related_name="exception_links"
    )
    relationship = models.CharField(max_length=16, choices=Relationship)

    class Meta:
        db_table = "exceptions_exception_source_link"
        constraints = [
            models.UniqueConstraint(
                fields=["exception_case", "source_record_version", "relationship"],
                name="uniq_case_source_relationship",
            )
        ]

    def __str__(self) -> str:
        return f"{self.relationship}: {self.source_record_version}"

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "exception_case", "source_record_version")


class ExceptionEvent(TenantScopedModel):
    """Append-only timeline entry (section 22.5).

    "The application provides no ordinary update/delete path for timeline events."
    """

    class ActorKind(models.TextChoices):
        MEMBERSHIP = "membership", "Member"
        WORKER = "worker", "Worker"
        DETECTOR = "detector", "Detector"
        SYSTEM = "system", "System"

    exception_case = models.ForeignKey(
        ExceptionCase, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=64)
    from_state = models.CharField(max_length=24, choices=CaseState, blank=True)
    to_state = models.CharField(max_length=24, choices=CaseState, blank=True)
    actor_kind = models.CharField(max_length=16, choices=ActorKind)
    actor_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="exception_events",
    )
    actor_worker_id = models.UUIDField(null=True, blank=True)
    actor_rule = models.CharField(max_length=96, blank=True)
    reason_code = models.CharField(max_length=40, blank=True)
    note = models.CharField(max_length=1000, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)
    request_id = models.CharField(max_length=64, blank=True)
    case_version = models.PositiveIntegerField()

    class Meta:
        db_table = "exceptions_exception_event"
        constraints = [
            models.CheckConstraint(
                condition=(
                    (
                        Q(actor_kind="membership")
                        & Q(actor_membership__isnull=False)
                        & Q(actor_worker_id__isnull=True)
                    )
                    | (
                        Q(actor_kind="worker")
                        & Q(actor_worker_id__isnull=False)
                        & Q(actor_membership__isnull=True)
                    )
                    | (
                        Q(actor_kind__in=["detector", "system"])
                        & Q(actor_membership__isnull=True)
                        & Q(actor_worker_id__isnull=True)
                        & ~Q(actor_rule="")
                    )
                ),
                name="ck_exception_event_exactly_one_actor",
            )
        ]
        ordering = ["occurred_at", "id"]

    def __str__(self) -> str:
        return f"{self.event_type} ({self.from_state or '-'} -> {self.to_state or '-'})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnlyError("ExceptionEvent rows are append-only and cannot be updated.")
        from apps.audit.models import validate_metadata

        validate_metadata(self.metadata)
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any):
        raise AppendOnlyError("ExceptionEvent rows are append-only and cannot be deleted.")


# ------------------------------------------------------------------ financial


class FinancialImpactSnapshot(TenantScopedModel):
    """A versioned, immutable financial calculation (section 22.5).

    "Never fill a monetary field without the required source basis. Unknown is NULL,
    not zero." A changed source or rule appends a new version; nothing overwrites.
    """

    class Basis(models.TextChoices):
        FIXED_WORK_ORDER = "fixed_work_order", "Fixed work-order amount"
        HOURLY_ACTUAL = "hourly_actual", "Approved hours x bill rate"
        HOURLY_SCHEDULED = "hourly_scheduled", "Scheduled hours x bill rate"
        MANUAL_AMOUNT_REQUIRED = "manual_amount_required", "Manual amount required"

    exception_case = models.ForeignKey(
        ExceptionCase, on_delete=models.CASCADE, related_name="financial_snapshots"
    )
    snapshot_version = models.PositiveIntegerField()
    calculation_code = models.CharField(max_length=64)
    calculation_version = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="USD")
    candidate_value = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, null=True, blank=True
    )
    invoice_ready_value = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, null=True, blank=True
    )
    basis = models.CharField(max_length=32, choices=Basis)
    assumptions = models.JSONField(default=dict, blank=True)
    calculated_at = models.DateTimeField(auto_now_add=True)
    calculated_by_rule = models.CharField(max_length=96)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_snapshots",
    )

    class Meta:
        db_table = "exceptions_financial_impact_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=["exception_case", "snapshot_version"], name="uniq_snapshot_version_per_case"
            ),
            models.CheckConstraint(
                condition=Q(candidate_value__isnull=True) | Q(candidate_value__gte=0),
                name="ck_snapshot_candidate_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(invoice_ready_value__isnull=True) | Q(invoice_ready_value__gte=0),
                name="ck_snapshot_ready_non_negative",
            ),
            # A manual-review basis can never carry a computed candidate value.
            models.CheckConstraint(
                condition=~Q(basis="manual_amount_required") | Q(candidate_value__isnull=True),
                name="ck_snapshot_manual_basis_has_no_value",
            ),
            # ...nor an approved one. Without this, a manual-amount case could be
            # approved and exported carrying a value nothing in the source supports.
            models.CheckConstraint(
                condition=~Q(basis="manual_amount_required") | Q(invoice_ready_value__isnull=True),
                name="ck_snapshot_manual_basis_has_no_ready_value",
            ),
        ]
        ordering = ["exception_case", "snapshot_version"]

    def __str__(self) -> str:
        return f"snapshot v{self.snapshot_version} ({self.basis})"

    #: Everything that defines what the money means. Only `approved_at`/`approved_by`
    #: may be written after creation, and only once, by the approval service.
    IMMUTABLE_FIELDS = (
        "candidate_value",
        "invoice_ready_value",
        "basis",
        "assumptions",
        "currency",
        "calculation_code",
        "calculation_version",
        "snapshot_version",
        "exception_case_id",
        "organization_id",
    )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            # Approval (Phase 6) sets approved_at/approved_by; values never change.
            original = FinancialImpactSnapshot.objects.get(pk=self.pk)
            changed = [
                name
                for name in self.IMMUTABLE_FIELDS
                if getattr(original, name) != getattr(self, name)
            ]
            if changed:
                raise AppendOnlyError(
                    "A financial snapshot's values are immutable; append a new version. "
                    f"Refused change to: {', '.join(changed)}."
                )
        super().save(*args, **kwargs)


class FinancialRecoveryItem(TenantScopedModel, VersionedModel):
    """The financial lifecycle, separate from the case lifecycle (section 22.5).

    Phase 4 populates the CANDIDATE stage only. Workflow transitions beyond candidate,
    the export reference, and the invoice-ready snapshot belong to Phase 6.
    """

    class WorkflowState(models.TextChoices):
        CANDIDATE = "candidate", "Candidate"
        INVOICE_READY = "invoice_ready", "Invoice-ready"
        EXPORTED = "exported", "Exported"
        VOID = "void", "Void"

    class AccountingStage(models.TextChoices):
        NO_INVOICE = "no_invoice", "No invoice"
        INVOICED = "invoiced", "Invoiced"
        PARTIALLY_COLLECTED = "partially_collected", "Partially collected"
        COLLECTED = "collected", "Collected"

    class DisputeStatus(models.TextChoices):
        CLEAR = "clear", "Clear"
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    exception_case = models.OneToOneField(
        ExceptionCase, on_delete=models.PROTECT, related_name="recovery_item"
    )
    work_order = models.ForeignKey(
        "operations.WorkOrder", on_delete=models.PROTECT, related_name="recovery_items"
    )
    workflow_state = models.CharField(
        max_length=16, choices=WorkflowState, default=WorkflowState.CANDIDATE
    )
    accounting_stage = models.CharField(
        max_length=24, choices=AccountingStage, default=AccountingStage.NO_INVOICE
    )
    dispute_status = models.CharField(
        max_length=16, choices=DisputeStatus, default=DisputeStatus.CLEAR
    )
    dispute_reason = models.CharField(max_length=500, blank=True)

    current_candidate_snapshot = models.ForeignKey(
        FinancialImpactSnapshot, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    current_invoice_ready_snapshot = models.ForeignKey(
        FinancialImpactSnapshot, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    actual_invoiced_amount = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, null=True, blank=True
    )
    actual_collected_amount = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, null=True, blank=True
    )
    export_reference = models.CharField(max_length=128, blank=True)

    class Meta:
        db_table = "exceptions_financial_recovery_item"
        constraints = [
            # One active item per work order. A void item releases the slot.
            models.UniqueConstraint(
                fields=["organization", "work_order"],
                condition=~Q(workflow_state="void"),
                name="uniq_active_recovery_item_per_work_order",
            ),
            models.CheckConstraint(
                condition=~Q(dispute_status="open") | ~Q(dispute_reason=""),
                name="ck_open_dispute_has_reason",
            ),
        ]

    def __str__(self) -> str:
        return f"recovery {self.workflow_state}/{self.accounting_stage}"

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "exception_case", "work_order")
        if (
            self.exception_case_id
            and self.work_order_id
            and self.exception_case.work_order_id != self.work_order_id
        ):
            raise ValidationError("The recovery item must reference the case's own work order.")
