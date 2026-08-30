"""Commercial-cleaning operational domain (master prompt section 22.4).

Route B scope. Present: the customer -> site -> contract -> obligation -> work order ->
accounting invoice/payment chain that Journey B ("completed but not invoiced") needs.

Deliberately absent, with no placeholder (Phase 0A matrix, line 2296): Worker,
QualificationType, SiteRequirement, WorkerQualification, WorkerSiteAuthorization,
WorkerAvailabilityWindow, Shift, TimeEntry, QualityEvent, and SiteOperationalRule.
Every field of SiteOperationalRule is an attendance or quality input; the revenue
detector's delay comes from ServiceObligation.uninvoiced_delay_days instead.

Source-system identity lives in ingestion.ExternalEntityReference, never on these
models: section 22.1 requires that canonical models not assume one source owns their
identity.
"""

from __future__ import annotations

import datetime as dt

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import (
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
    RATE_DECIMAL_PLACES,
    RATE_MAX_DIGITS,
    TenantScopedModel,
)
from apps.common.validators import assert_same_organization, validate_iana_timezone


class CustomerAccount(TenantScopedModel):
    """A cleaning customer. No sensitive contact data is needed for the demo."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        ENDED = "ended", "Ended"

    name = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE)
    account_reference = models.CharField(
        max_length=64, blank=True, help_text="Safe internal reference. Never a credential."
    )

    class Meta:
        db_table = "operations_customer_account"
        constraints = [
            # Organization-scoped, never global: two tenants may both have a customer
            # named "Meridian Property Group" (section 17, rule 3).
            models.UniqueConstraint(
                fields=["organization", "name"], name="uniq_customer_name_per_org"
            )
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Site(TenantScopedModel):
    """A serviced location.

    Section 22.4 forbids storing alarm codes, keys, detailed access instructions, or
    real addresses in the demo. `region_code` is a coarse operational region only.

    `timezone` is load-bearing, not cosmetic: the accounting reconciliation converts
    instants to site-local calendar dates, so an incorrect timezone changes which
    invoices are considered in scope.
    """

    class SiteType(models.TextChoices):
        OFFICE = "office", "Office"
        RETAIL = "retail", "Retail"
        LIGHT_INDUSTRIAL = "light_industrial", "Light industrial"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        ENDED = "ended", "Ended"

    customer = models.ForeignKey(CustomerAccount, on_delete=models.PROTECT, related_name="sites")
    name = models.CharField(max_length=200)
    timezone = models.CharField(
        max_length=64,
        validators=[validate_iana_timezone],
        help_text="IANA timezone. Used to convert instants to site-local service dates.",
    )
    region_code = models.CharField(
        max_length=32, blank=True, help_text="Coarse operational region, never a home address."
    )
    site_type = models.CharField(max_length=24, choices=SiteType, default=SiteType.OFFICE)
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE)

    class Meta:
        db_table = "operations_site"
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="uniq_site_name_per_org")
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()
        validate_iana_timezone(self.timezone)
        assert_same_organization(self, "customer")


class Contract(TenantScopedModel):
    """A commercial agreement with one customer, covering one or more sites."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        ENDED = "ended", "Ended"

    customer = models.ForeignKey(
        CustomerAccount, on_delete=models.PROTECT, related_name="contracts"
    )
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE)
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="USD")
    contract_reference = models.CharField(
        max_length=64, blank=True, help_text="Safe reference. Never upload a real contract."
    )

    class Meta:
        db_table = "operations_contract"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_on__isnull=True)
                | models.Q(ends_on__gte=models.F("starts_on")),
                name="ck_contract_end_not_before_start",
            )
        ]
        ordering = ["-starts_on"]

    def __str__(self) -> str:
        return self.contract_reference or f"Contract {self.pk}"

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "customer")

    def is_active_on(self, service_date: dt.date) -> bool:
        """Detector condition 6: the contract must be active for the service date."""
        if self.status != self.Status.ACTIVE:
            return False
        if service_date < self.starts_on:
            return False
        return not (self.ends_on and service_date > self.ends_on)


class ContractSite(TenantScopedModel):
    """Links a contract to a site for an effective period.

    Effective ranges are half-open [effective_from, effective_to): a row whose
    effective_to equals the next row's effective_from does not overlap it.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ENDED = "ended", "Ended"

    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name="contract_sites")
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="contract_sites")
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "operations_contract_site"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_from")),
                name="ck_contract_site_period_ordered",
            ),
            models.UniqueConstraint(
                fields=["organization", "contract", "site", "effective_from"],
                name="uniq_contract_site_effective_from",
            ),
        ]
        ordering = ["site__name", "-effective_from"]

    def __str__(self) -> str:
        return f"{self.contract} @ {self.site}"

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "contract", "site")
        self._reject_overlapping_period()

    def _reject_overlapping_period(self) -> None:
        """No two rows for the same contract/site may cover the same day.

        A PostgreSQL exclusion constraint over a daterange would express this in the
        database, but it requires the btree_gist extension and a generated range
        column. That is deferred to a dedicated migration; until then this is service
        validation backed by tests, which is what section 22.1 permits.
        """
        if not (self.contract_id and self.site_id and self.effective_from):
            return
        siblings = ContractSite.objects.filter(
            organization_id=self.organization_id,
            contract_id=self.contract_id,
            site_id=self.site_id,
        ).exclude(pk=self.pk)
        for other in siblings:
            starts_before_other_ends = (
                other.effective_to is None or self.effective_from < other.effective_to
            )
            other_starts_before_this_ends = (
                self.effective_to is None or other.effective_from < self.effective_to
            )
            if starts_before_other_ends and other_starts_before_this_ends:
                raise ValidationError(
                    {"effective_from": "This period overlaps an existing contract-site period."}
                )


class ServiceObligation(TenantScopedModel):
    """What is owed at one contract-site: scope, window, coverage, and billing basis.

    Section 22.4: "This is the minimum scope model needed to decide whether coverage,
    quality, or extra work matters. It is not a full janitorial workloading engine."

    `uninvoiced_delay_days` is the input to REVENUE_COMPLETED_UNBILLED_V1 condition 3 —
    the grace period after completion before unbilled work becomes a candidate.

    Route B omission: the optional quality-criterion code and default response/
    correction minutes named in section 22.4 are not modelled, because Journey C is
    unbuilt and no Route B CSV column supplies them. Evidence expansion step E1 adds
    them if Journey C is approved.
    """

    class ScopeKind(models.TextChoices):
        BASE_RECURRING = "base_recurring", "Base recurring"
        AUTHORIZED_EXTRA = "authorized_extra", "Authorized extra"
        PERIODIC = "periodic", "Periodic"
        CORRECTIVE = "corrective", "Corrective"

    class BillingBasis(models.TextChoices):
        INCLUDED = "included", "Included in base contract"
        FIXED_WORK_ORDER = "fixed_work_order", "Fixed amount per work order"
        HOURLY_ACTUAL = "hourly_actual", "Hourly on actual hours"
        HOURLY_SCHEDULED = "hourly_scheduled", "Hourly on scheduled hours"
        MANUAL_REVIEW = "manual_review", "Manual review required"

    contract_site = models.ForeignKey(
        ContractSite, on_delete=models.PROTECT, related_name="service_obligations"
    )
    code = models.CharField(max_length=64)
    label = models.CharField(max_length=200)
    service_type = models.CharField(max_length=64, help_text="Customer-defined controlled code.")
    scope_kind = models.CharField(max_length=24, choices=ScopeKind)

    # Site-local times. end < start is legitimate and means the window crosses
    # midnight; no ordering constraint is applied for that reason.
    service_window_start = models.TimeField()
    service_window_end = models.TimeField()
    service_weekdays = models.CharField(
        max_length=32,
        help_text="Comma-separated weekday codes, e.g. 'mon,tue,wed'. Explicit, never inferred.",
    )

    role_code = models.CharField(max_length=64)
    required_coverage_count = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    substitution_required_when_below_count = models.BooleanField()

    billing_basis = models.CharField(max_length=24, choices=BillingBasis)
    default_bill_rate = models.DecimalField(
        max_digits=RATE_MAX_DIGITS,
        decimal_places=RATE_DECIMAL_PLACES,
        null=True,
        blank=True,
        help_text="NULL means unknown, never zero (section 18).",
    )
    extra_work_requires_authorization = models.BooleanField()
    uninvoiced_delay_days = models.PositiveIntegerField(
        help_text="Days after completion before unbilled work becomes a candidate."
    )

    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    rule_version = models.PositiveIntegerField(default=1)
    change_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "operations_service_obligation"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "contract_site", "code", "effective_from"],
                name="uniq_obligation_per_site_code_effective",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_from")),
                name="ck_obligation_period_ordered",
            ),
            models.CheckConstraint(
                condition=models.Q(required_coverage_count__gte=1),
                name="ck_obligation_coverage_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(uninvoiced_delay_days__lte=365),
                name="ck_obligation_delay_within_year",
            ),
            # Unknown is NULL; a negative rate is never meaningful.
            models.CheckConstraint(
                condition=models.Q(default_bill_rate__isnull=True)
                | models.Q(default_bill_rate__gte=0),
                name="ck_obligation_rate_non_negative",
            ),
        ]
        ordering = ["contract_site", "code", "-effective_from"]

    def __str__(self) -> str:
        return f"{self.code} — {self.label}"

    @property
    def crosses_midnight(self) -> bool:
        return self.service_window_end < self.service_window_start

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "contract_site")
        if (
            self.billing_basis
            in (
                self.BillingBasis.HOURLY_ACTUAL,
                self.BillingBasis.HOURLY_SCHEDULED,
            )
            and self.default_bill_rate is None
        ):
            raise ValidationError(
                {"default_bill_rate": "An hourly billing basis requires a bill rate."}
            )


class WorkOrder(TenantScopedModel):
    """Billable or non-billable work recorded by an operations source.

    Financial fields may be null. Section 22.4 is explicit: "Missing evidence must block
    invoice-ready approval, not trigger a guessed value."
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        VOID = "void", "Void"

    customer = models.ForeignKey(
        CustomerAccount, on_delete=models.PROTECT, related_name="work_orders"
    )
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="work_orders")
    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name="work_orders")
    service_obligation = models.ForeignKey(
        ServiceObligation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="work_orders",
    )

    title = models.CharField(max_length=200, help_text="Safe scope summary. Synthetic in demo.")
    scheduled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.OPEN)

    billable = models.BooleanField()
    authorization_required = models.BooleanField(default=False)
    authorization_reference = models.CharField(max_length=128, blank=True)
    authorized_at = models.DateTimeField(null=True, blank=True)

    billing_basis = models.CharField(
        max_length=24, choices=ServiceObligation.BillingBasis, blank=True
    )
    approved_fixed_amount = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, null=True, blank=True
    )
    approved_hours = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    bill_rate = models.DecimalField(
        max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES, null=True, blank=True
    )

    source_as_of_at = models.DateTimeField(help_text="Freshness of the observing source.")

    class Meta:
        db_table = "operations_work_order"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(approved_fixed_amount__isnull=True)
                | models.Q(approved_fixed_amount__gte=0),
                name="ck_work_order_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(approved_hours__isnull=True) | models.Q(approved_hours__gte=0),
                name="ck_work_order_hours_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(bill_rate__isnull=True) | models.Q(bill_rate__gte=0),
                name="ck_work_order_rate_non_negative",
            ),
            # A completed work order must say when it completed; the detector reads it.
            models.CheckConstraint(
                condition=~models.Q(status="completed") | models.Q(completed_at__isnull=False),
                name="ck_work_order_completed_has_timestamp",
            ),
        ]
        ordering = ["-completed_at", "-scheduled_at"]

    def __str__(self) -> str:
        return self.title

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "customer", "site", "contract", "service_obligation")

    @property
    def has_required_authorization(self) -> bool:
        """Detector condition 5: authorization reference and date present when required."""
        if not self.authorization_required:
            return True
        return bool(self.authorization_reference) and self.authorized_at is not None


class AccountingInvoice(TenantScopedModel):
    """An invoice observed in a separate accounting source.

    Section 22.4: "This is a separate accounting-source fact; do not copy invoice/
    payment state onto WorkOrder." The accounting system is not assumed to know what a
    work order is, so `work_order` is optional and reconciliation normally runs on the
    confirmed customer/site crosswalk plus `service_date`.

    Deduplication is by confirmed canonical identity in ExternalEntityReference, never
    by `invoice_reference`, which is only a display value.
    """

    class SourceStatus(models.TextChoices):
        POSTED = "posted", "Posted"
        VOID = "void", "Void"
        DISPUTED = "disputed", "Disputed"

    customer = models.ForeignKey(
        CustomerAccount, on_delete=models.PROTECT, related_name="accounting_invoices"
    )
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="accounting_invoices")
    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accounting_invoices",
        help_text="Set only when a confirmed mapping resolves to exactly one work order.",
    )
    service_date = models.DateField(help_text="Site-local calendar date used in reconciliation.")
    invoice_reference = models.CharField(max_length=128)
    invoice_amount = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    invoiced_at = models.DateTimeField()
    currency = models.CharField(max_length=3, default="USD")
    source_status = models.CharField(max_length=16, choices=SourceStatus)
    source_as_of_at = models.DateTimeField()

    class Meta:
        db_table = "operations_accounting_invoice"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(invoice_amount__gte=0),
                name="ck_invoice_amount_non_negative",
            )
        ]
        ordering = ["-invoiced_at"]

    def __str__(self) -> str:
        return f"Invoice {self.invoice_reference}"

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "customer", "site", "work_order")

    @property
    def counts_toward_actuals(self) -> bool:
        """Only a posted invoice contributes to actual invoiced value (section 23.1)."""
        return self.source_status == self.SourceStatus.POSTED


class AccountingPayment(TenantScopedModel):
    """A payment observed in the accounting source, always attached to one invoice.

    One invoice may have several distinct payments. Section 22.4 lists what the demo
    deliberately does NOT support and which must instead open a blocking reconciliation
    issue: credits, refunds, negative amounts, cross-currency allocation, and one
    payment spanning multiple invoices.
    """

    class SourceStatus(models.TextChoices):
        POSTED = "posted", "Posted"
        REVERSED = "reversed", "Reversed"
        DISPUTED = "disputed", "Disputed"

    accounting_invoice = models.ForeignKey(
        AccountingInvoice, on_delete=models.PROTECT, related_name="payments"
    )
    payment_reference = models.CharField(max_length=128)
    collected_amount = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    collected_at = models.DateTimeField()
    currency = models.CharField(max_length=3, default="USD")
    source_status = models.CharField(max_length=16, choices=SourceStatus)
    source_as_of_at = models.DateTimeField()

    class Meta:
        db_table = "operations_accounting_payment"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(collected_amount__gte=0),
                name="ck_payment_amount_non_negative",
            )
        ]
        ordering = ["-collected_at"]

    def __str__(self) -> str:
        return f"Payment {self.payment_reference}"

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "accounting_invoice")
        if self.accounting_invoice_id and self.currency != self.accounting_invoice.currency:
            # Cross-currency allocation is unsupported in the demo and must surface as
            # a reconciliation issue rather than be silently converted.
            raise ValidationError({"currency": "Payment currency must match the invoice currency."})
