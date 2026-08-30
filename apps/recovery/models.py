"""Approvals, finance exports, and financial stage history (sections 22.5, 22.6).

Route B revenue subset. Present: the approval that moves a recovery item from
`candidate` to `invoice_ready`, the export record behind the protected download, and
the append-only stage history section 22.5 requires.

Deliberately absent (Route B override, line 2690): EvidenceArtifact and any arbitrary
evidence handling, client-notification state, and every Journey C model. Phase 5 was
skipped, so there is no RecommendationSet or ProposedAction for an Approval to point at.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.common.models import MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS, TenantScopedModel
from apps.common.validators import assert_same_organization


class AppendOnlyError(RuntimeError):
    pass


class Approval(TenantScopedModel):
    """A named human decision (section 22.6).

    Section 22.6 requires "exactly one typed subject foreign key among
    recommendation_set, proposed_action, or financial_recovery_item, plus
    subject_version". The first two belong to Phase 5, which Route B skips; rather than
    create placeholder columns for models that do not exist, only the reachable subject
    is modelled and the check constraint asserts it is present. Evidence expansion step
    E3 adds the other two columns and widens the constraint.
    """

    class ApprovalType(models.TextChoices):
        INVOICE_READY = "invoice_ready", "Invoice-ready value"
        FINANCE_EXPORT = "finance_export", "Finance export"
        CASE_RESOLUTION = "case_resolution", "Case resolution"
        # draft_handoff, proposed_assignment and corrective_action are Journey A/C and
        # are not reachable in this slice.

    class Decision(models.TextChoices):
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        REVOKED = "revoked", "Revoked"

    exception_case = models.ForeignKey(
        "exceptions.ExceptionCase", on_delete=models.PROTECT, related_name="approvals"
    )
    approval_type = models.CharField(max_length=32, choices=ApprovalType)
    decision = models.CharField(max_length=16, choices=Decision)

    financial_recovery_item = models.ForeignKey(
        "exceptions.FinancialRecoveryItem",
        on_delete=models.PROTECT,
        related_name="approvals",
        help_text="The only approval subject reachable in the Route B slice.",
    )
    subject_version = models.PositiveIntegerField(
        help_text="The subject's version at decision time; a stale value is refused."
    )
    #: The snapshot the approver actually saw. Section 23.1 requires a "current
    #: immutable calculation snapshot" for the candidate -> invoice_ready transition.
    financial_snapshot = models.ForeignKey(
        "exceptions.FinancialImpactSnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approvals",
    )
    #: What the checklist reported at decision time, so the decision can be audited
    #: later even if the underlying data changes.
    evidence_snapshot = models.JSONField(default=dict, blank=True)

    decided_by = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="approvals_made"
    )
    decided_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=1000, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approvals_revoked",
    )

    class Meta:
        db_table = "recovery_approval"
        constraints = [
            # One live approval of each type per subject. A revoked approval frees the
            # slot so a corrected snapshot can be re-approved (section 23.1 line 1388).
            models.UniqueConstraint(
                fields=["financial_recovery_item", "approval_type"],
                condition=Q(decision="approved") & Q(revoked_at__isnull=True),
                name="uniq_live_approval_per_subject_type",
            ),
            models.CheckConstraint(
                condition=~Q(decision="revoked") | Q(revoked_at__isnull=False),
                name="ck_revoked_approval_has_timestamp",
            ),
            # An invoice-ready approval must name the snapshot it approved.
            models.CheckConstraint(
                condition=~(Q(approval_type="invoice_ready") & Q(decision="approved"))
                | Q(financial_snapshot__isnull=False),
                name="ck_invoice_ready_approval_names_snapshot",
            ),
        ]
        ordering = ["-decided_at"]

    def __str__(self) -> str:
        return f"{self.approval_type} {self.decision}"

    @property
    def is_live(self) -> bool:
        return self.decision == self.Decision.APPROVED and self.revoked_at is None

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "exception_case", "financial_recovery_item", "decided_by")
        if (
            self.financial_recovery_item_id
            and self.exception_case_id
            and self.financial_recovery_item.exception_case_id != self.exception_case_id
        ):
            raise ValidationError("The approval subject must belong to the named case.")


class FinanceExport(TenantScopedModel):
    """One generated invoice-ready CSV (section 29 route, section 23.1 line 1386).

    Section 22 defines no export model even though four separate places assume one:
    the `/app/exports/<uuid>/download/` route, "Export record and protected download"
    (line 2700), the `invoice_ready -> exported` transition requiring "one idempotent
    export reference", and section 18's "internal handoff/export idempotency uses a
    stable event key and database uniqueness". ADR 0008 records the decision to add it.

    The CSV bytes are stored on the row rather than on disk: EVIDENCE_MODE is
    metadata_only and arbitrary file storage is rejected through Phase 8. This is
    system-generated content from records already held, not uploaded evidence.
    """

    idempotency_key = models.CharField(
        max_length=64, help_text="Stable hash of the exported item set and their approvals."
    )
    content_sha256 = models.CharField(max_length=64)
    content = models.TextField(help_text="The generated CSV. Regenerating never changes it.")
    row_count = models.PositiveIntegerField()
    total_invoice_ready_value = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        help_text="Sum of the exported invoice-ready values ONLY. Never a cross-stage total.",
    )
    currency = models.CharField(max_length=3, default="USD")
    created_by = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="finance_exports"
    )
    items = models.ManyToManyField(
        "exceptions.FinancialRecoveryItem", related_name="exports", blank=True
    )
    superseded_note = models.CharField(
        max_length=500,
        blank=True,
        help_text="Set when a source correction arrived after export. The export is retained.",
    )

    class Meta:
        db_table = "recovery_finance_export"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"], name="uniq_finance_export_idempotency"
            ),
            models.CheckConstraint(
                condition=Q(total_invoice_ready_value__gte=0),
                name="ck_export_total_non_negative",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"export {self.idempotency_key[:12]} ({self.row_count} rows)"

    @property
    def filename(self) -> str:
        return f"invoice-ready-{self.created_at:%Y%m%d-%H%M%S}.csv"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            original = FinanceExport.objects.get(pk=self.pk)
            if original.content_sha256 != self.content_sha256 or original.content != self.content:
                raise AppendOnlyError(
                    "An export's content is immutable; a correction creates a new export."
                )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any):
        raise AppendOnlyError("An export is retained for audit and cannot be deleted.")


class FinancialStageEvent(TenantScopedModel):
    """Append-only financial stage history (section 22.5, line 1241).

    "append-only stage events with source/user provenance". Every workflow transition
    and every accounting-stage change appends one; nothing is ever rewritten.
    """

    class Kind(models.TextChoices):
        WORKFLOW = "workflow", "Workflow state change"
        ACCOUNTING = "accounting", "Accounting stage change"
        DISPUTE = "dispute", "Dispute opened or resolved"

    financial_recovery_item = models.ForeignKey(
        "exceptions.FinancialRecoveryItem", on_delete=models.CASCADE, related_name="stage_events"
    )
    kind = models.CharField(max_length=16, choices=Kind)
    from_value = models.CharField(max_length=32, blank=True)
    to_value = models.CharField(max_length=32)
    reason_code = models.CharField(max_length=64, blank=True)
    note = models.CharField(max_length=500, blank=True)
    actor_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stage_events",
    )
    actor_rule = models.CharField(max_length=96, blank=True)
    source_invoice = models.ForeignKey(
        "operations.AccountingInvoice",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stage_events",
    )
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "recovery_financial_stage_event"
        constraints = [
            # Exactly one actor: a person or a rule, never both, never neither.
            models.CheckConstraint(
                condition=(
                    (Q(actor_membership__isnull=False) & Q(actor_rule=""))
                    | (Q(actor_membership__isnull=True) & ~Q(actor_rule=""))
                ),
                name="ck_stage_event_exactly_one_actor",
            )
        ]
        ordering = ["occurred_at", "id"]

    def __str__(self) -> str:
        return f"{self.kind}: {self.from_value or '-'} -> {self.to_value}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnlyError("Stage events are append-only and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any):
        raise AppendOnlyError("Stage events are append-only and cannot be deleted.")
