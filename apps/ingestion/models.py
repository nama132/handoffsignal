"""Source ownership, cross-system identity, and reconciliation (section 22.3).

Identity is a product feature, not an import convenience (section 12, principle 15):
"Different source systems are not assumed to share customer, site, worker, contract,
work-order, or invoice IDs; unresolved mappings stay visible and block dependent
decisions."

Phase 3 owns ImportBatch, ImportCoverage, ImportRow, SourceRecordVersion, and
ReconciliationRun. Two models here (IdentityResolutionIssue, ReconciliationIssue) are
described in section 22.3 as referencing a source record version; because that model
arrives in Phase 3, they record the supplied source and external identifier now, and
Phase 3 adds the version link. This is recorded in docs/BUILD_STATUS.md rather than
silently deferred.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.common.models import TenantScopedModel
from apps.common.validators import assert_same_organization

#: Canonical targets an external reference may resolve to under Route B. The section
#: 22.3 list also names worker, availability_window, shift, time_entry, and
#: quality_event; those models are not built, so no column exists for them and a CSV
#: naming one is rejected rather than silently accepted.
TARGET_FIELDS: tuple[str, ...] = (
    "customer",
    "site",
    "contract",
    "service_obligation",
    "work_order",
    "accounting_invoice",
    "accounting_payment",
)


def _all_targets_null() -> Q:
    q = Q()
    for field in TARGET_FIELDS:
        q &= Q(**{f"{field}__isnull": True})
    return q


def _exactly_one_target() -> Q:
    """Q matching rows where exactly one typed target column is populated."""
    combined = Q()
    for field in TARGET_FIELDS:
        clause = Q(**{f"{field}__isnull": False})
        for other in TARGET_FIELDS:
            if other != field:
                clause &= Q(**{f"{other}__isnull": True})
        combined |= clause
    return combined


class DataSource(TenantScopedModel):
    """One declared feed from one source system.

    `system_key` is an owner-defined namespace and does not imply a vendor integration.
    Two feeds from the same vendor need distinct keys (section 22.3, line 851), because
    a CSV's `*_source_system` column resolves this key with no hidden domain qualifier.
    """

    class SourceType(models.TextChoices):
        CSV = "csv", "CSV export"
        # api and sftp exist in the vocabulary but are not implemented and require
        # approval before use (section 22.3).

    class Domain(models.TextChoices):
        CONTRACTS = "contracts", "Contracts and scope"
        IDENTITY_CROSSWALK = "identity_crosswalk", "Identity crosswalk"
        WORKERS = "workers", "Workers and eligibility"
        SCHEDULE = "schedule", "Scheduled shifts"
        TIME = "time", "Time entries"
        SERVICE_EVENTS = "service_events", "Work orders and service events"
        INVOICE_STATUS = "invoice_status", "Accounting invoice status"

    name = models.CharField(max_length=200)
    source_type = models.CharField(max_length=16, choices=SourceType, default=SourceType.CSV)
    system_key = models.SlugField(
        max_length=64, help_text="Immutable owner-defined namespace. Not a vendor claim."
    )
    domain = models.CharField(max_length=32, choices=Domain)
    expected_cadence_minutes = models.PositiveIntegerField(null=True, blank=True)
    maximum_age_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Beyond this age the source is stale and time-sensitive detection is suppressed.",
    )
    is_authoritative = models.BooleanField(
        default=False, help_text="Authoritative for its declared fields only."
    )
    last_successful_import_at = models.DateTimeField(null=True, blank=True)
    last_source_as_of_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ingestion_data_source"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "system_key"], name="uniq_source_key_per_org"
            )
        ]
        ordering = ["system_key"]

    def __str__(self) -> str:
        return self.system_key


class ExternalEntityReference(TenantScopedModel):
    """Maps one source system's identifier to one canonical entity.

    Section 22.3 states the invariants this class enforces in the database:

    * `confirmed` has exactly one typed target;
    * `unresolved` and `rejected` have zero;
    * `superseded` may retain zero or one historical target but is never current;
    * a source reference cannot map to more than one *current* canonical object.

    Fuzzy or AI matching may never auto-confirm (line 938); `match_method` has no
    value permitting it.
    """

    class MappingStatus(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        UNRESOLVED = "unresolved", "Unresolved"
        REJECTED = "rejected", "Rejected"
        SUPERSEDED = "superseded", "Superseded"

    class MatchMethod(models.TextChoices):
        PARTNER_CANONICAL_KEY = "partner_canonical_key", "Partner canonical key"
        MANUAL = "manual", "Manually confirmed"
        DETERMINISTIC_EXACT = "deterministic_exact", "Deterministic exact match"

    class EntityType(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        SITE = "site", "Site"
        CONTRACT = "contract", "Contract"
        SERVICE_OBLIGATION = "service_obligation", "Service obligation"
        WORK_ORDER = "work_order", "Work order"
        ACCOUNTING_INVOICE = "accounting_invoice", "Accounting invoice"
        ACCOUNTING_PAYMENT = "accounting_payment", "Accounting payment"

    source = models.ForeignKey(
        DataSource, on_delete=models.PROTECT, related_name="entity_references"
    )
    entity_type = models.CharField(max_length=32, choices=EntityType)
    external_id = models.CharField(max_length=128)
    mapping_status = models.CharField(
        max_length=16, choices=MappingStatus, default=MappingStatus.UNRESOLVED
    )
    match_method = models.CharField(max_length=32, choices=MatchMethod, blank=True)
    mapping_provenance = models.CharField(
        max_length=200, blank=True, help_text="Source file/batch/row or named user."
    )
    confirmed_by = models.ForeignKey(
        "organizations.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="identity_confirmations",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    supersedes = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="superseded_by"
    )

    # Typed canonical targets. Exactly one is populated when confirmed.
    customer = models.ForeignKey(
        "operations.CustomerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="external_references",
    )
    site = models.ForeignKey(
        "operations.Site",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="external_references",
    )
    contract = models.ForeignKey(
        "operations.Contract",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="external_references",
    )
    service_obligation = models.ForeignKey(
        "operations.ServiceObligation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="external_references",
    )
    work_order = models.ForeignKey(
        "operations.WorkOrder",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="external_references",
    )
    accounting_invoice = models.ForeignKey(
        "operations.AccountingInvoice",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="external_references",
    )
    accounting_payment = models.ForeignKey(
        "operations.AccountingPayment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="external_references",
    )

    class Meta:
        db_table = "ingestion_external_entity_reference"
        constraints = [
            # One CURRENT reference per (org, source, entity_type, external_id).
            # Superseded rows are excluded so history can accumulate.
            models.UniqueConstraint(
                fields=["organization", "source", "entity_type", "external_id"],
                condition=~Q(mapping_status="superseded"),
                name="uniq_current_external_reference",
            ),
            models.CheckConstraint(
                condition=(
                    (Q(mapping_status="confirmed") & _exactly_one_target())
                    | (Q(mapping_status__in=["unresolved", "rejected"]) & _all_targets_null())
                    | (
                        Q(mapping_status="superseded")
                        & (_all_targets_null() | _exactly_one_target())
                    )
                ),
                name="ck_external_reference_typed_target",
            ),
            # A confirmed mapping must record who confirmed it and how.
            models.CheckConstraint(
                condition=~Q(mapping_status="confirmed")
                | (Q(confirmed_at__isnull=False) & ~Q(match_method="")),
                name="ck_confirmed_reference_has_provenance",
            ),
        ]
        ordering = ["entity_type", "external_id"]
        indexes = [
            models.Index(
                fields=["organization", "entity_type", "mapping_status"],
                name="idx_ext_ref_org_type_status",
            )
        ]

    def __str__(self) -> str:
        return f"{self.source_id}:{self.entity_type}:{self.external_id}"

    @property
    def is_current(self) -> bool:
        return self.mapping_status != self.MappingStatus.SUPERSEDED

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "source", *TARGET_FIELDS)
        populated = [f for f in TARGET_FIELDS if getattr(self, f"{f}_id", None) is not None]
        if self.mapping_status == self.MappingStatus.CONFIRMED and len(populated) != 1:
            raise ValidationError(
                {"mapping_status": "A confirmed reference must have exactly one canonical target."}
            )
        if (
            self.mapping_status
            in (
                self.MappingStatus.UNRESOLVED,
                self.MappingStatus.REJECTED,
            )
            and populated
        ):
            raise ValidationError(
                {"mapping_status": "An unresolved or rejected reference must have no target."}
            )
        # The declared entity_type must match whichever target column is populated.
        if populated and populated[0] != self.entity_type:
            raise ValidationError(
                {"entity_type": "The populated target does not match the declared entity type."}
            )


class IdentityResolutionIssue(TenantScopedModel):
    """A source reference that could not be resolved to exactly one canonical entity.

    Section 22.3: "Dependent rows remain quarantined and detectors cannot use them
    until all required references are confirmed."

    The `source_record_version` link was deferred in Phase 2 because SourceRecordVersion
    did not exist yet; Phase 3 adds it. It stays nullable: an issue can be raised for a
    row that never produced a version because it failed validation.
    """

    class Status(models.TextChoices):
        UNRESOLVED = "unresolved", "Unresolved"
        RESOLVED = "resolved", "Resolved"
        REJECTED = "rejected", "Rejected"

    class Reason(models.TextChoices):
        UNRESOLVED_IDENTITY = "unresolved_identity", "No candidate found"
        AMBIGUOUS_IDENTITY = "ambiguous_identity", "More than one candidate"
        CONFLICTING_CROSSWALK = "conflicting_crosswalk", "Conflicting crosswalk rows"
        CROSS_TENANT_REFERENCE = "cross_tenant_reference", "Reference crosses tenants"

    supplied_source = models.ForeignKey(
        DataSource, on_delete=models.PROTECT, related_name="identity_issues"
    )
    source_record_version = models.ForeignKey(
        "ingestion.SourceRecordVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="identity_issues",
        help_text="Null when the row failed validation before a version was written.",
    )
    import_batch = models.ForeignKey(
        "ingestion.ImportBatch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="identity_issues",
    )
    entity_type = models.CharField(max_length=32, choices=ExternalEntityReference.EntityType)
    supplied_external_id = models.CharField(max_length=128)
    reason_code = models.CharField(max_length=32, choices=Reason)
    status = models.CharField(max_length=16, choices=Status, default=Status.UNRESOLVED)
    candidate_reference_ids = models.JSONField(
        default=list, blank=True, help_text="Canonical UUIDs considered. Deterministic only."
    )
    explanation = models.TextField(blank=True, help_text="Safe explanation. Never a raw row.")
    resolved_reference = models.ForeignKey(
        ExternalEntityReference,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="resolved_issues",
    )
    resolved_by = models.ForeignKey(
        "organizations.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="identity_issues_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "ingestion_identity_resolution_issue"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "supplied_source", "entity_type", "supplied_external_id"],
                condition=Q(status="unresolved"),
                name="uniq_open_identity_issue",
            ),
            # A resolved or rejected issue must record who decided and when.
            models.CheckConstraint(
                condition=Q(status="unresolved")
                | (Q(resolved_by__isnull=False) & Q(resolved_at__isnull=False)),
                name="ck_identity_issue_resolution_attributed",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.supplied_external_id} ({self.status})"

    @property
    def blocks_dependents(self) -> bool:
        return self.status == self.Status.UNRESOLVED

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "supplied_source", "resolved_reference")


class SourcePrecedenceRule(TenantScopedModel):
    """Which source wins for a field group, and what happens when they disagree.

    Section 22.3: "Defaults must be explicit; never use whichever file imported last as
    hidden precedence."
    """

    class FieldGroup(models.TextChoices):
        IDENTITY = "identity", "Identity"
        SCHEDULE_STATUS = "schedule_status", "Schedule status"
        COMPLETION = "completion", "Completion"
        CONTRACT_RATE = "contract_rate", "Contract and rate"
        INVOICE_STATUS = "invoice_status", "Invoice status"

    class ConflictPolicy(models.TextChoices):
        BLOCK_AND_REVIEW = "block_and_review", "Block and require review"
        PREFER_AUTHORITATIVE = "prefer_authoritative", "Prefer the authoritative source"
        LATEST_WITHIN_AUTHORITATIVE_SOURCE = (
            "latest_within_authoritative_source",
            "Latest within the authoritative source",
        )

    entity_type = models.CharField(max_length=32, choices=ExternalEntityReference.EntityType)
    field_group = models.CharField(max_length=32, choices=FieldGroup)
    conflict_policy = models.CharField(max_length=40, choices=ConflictPolicy)
    authoritative_sources = models.ManyToManyField(
        DataSource, through="SourcePrecedenceEntry", related_name="precedence_rules"
    )
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    rule_version = models.PositiveIntegerField(default=1)
    change_reason = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        "organizations.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="precedence_rules_created",
    )

    class Meta:
        db_table = "ingestion_source_precedence_rule"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "entity_type", "field_group", "effective_from"],
                name="uniq_precedence_rule_effective",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True)
                | Q(effective_to__gt=models.F("effective_from")),
                name="ck_precedence_period_ordered",
            ),
        ]
        ordering = ["entity_type", "field_group", "-effective_from"]

    def __str__(self) -> str:
        return f"{self.entity_type}/{self.field_group}"


class SourcePrecedenceEntry(TenantScopedModel):
    """One ordered authoritative source within a precedence rule.

    Section 22.3 requires "ordered/declared authoritative DataSource references"; rank
    makes that order explicit and queryable rather than implied by insertion.

    This is tenant-owned like every other operational row (section 17, rule 2). It was
    briefly modelled as a plain Model, which left nothing preventing an entry joining a
    rule in one organization to a DataSource in another - a cross-tenant edge through a
    join table. Both foreign keys are now validated against this row's own organization.
    """

    rule = models.ForeignKey(SourcePrecedenceRule, on_delete=models.CASCADE, related_name="entries")
    source = models.ForeignKey(
        DataSource, on_delete=models.PROTECT, related_name="precedence_entries"
    )
    rank = models.PositiveIntegerField(help_text="1 is highest precedence.")

    class Meta:
        db_table = "ingestion_source_precedence_entry"
        constraints = [
            models.UniqueConstraint(fields=["rule", "source"], name="uniq_precedence_rule_source"),
            models.UniqueConstraint(fields=["rule", "rank"], name="uniq_precedence_rule_rank"),
            models.CheckConstraint(condition=Q(rank__gte=1), name="ck_precedence_rank_positive"),
        ]
        ordering = ["rule", "rank"]

    def __str__(self) -> str:
        return f"{self.rule} #{self.rank} {self.source}"

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "rule", "source")


class ReconciliationIssue(TenantScopedModel):
    """Two sources disagree about the same canonical fact.

    Section 22.3: "A blocking conflict prevents dependent detector/financial approval
    until resolved." The conflicting-source-version links were deferred in Phase 2 and
    are added here as a many-to-many, because a conflict is by definition between two or
    more versions.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    field_group = models.CharField(max_length=32, choices=SourcePrecedenceRule.FieldGroup)
    entity_type = models.CharField(max_length=32, choices=ExternalEntityReference.EntityType)
    conflicting_source_versions = models.ManyToManyField(
        "ingestion.SourceRecordVersion", blank=True, related_name="reconciliation_issues"
    )
    status = models.CharField(max_length=16, choices=Status, default=Status.OPEN)
    is_blocking = models.BooleanField(
        default=True,
        help_text="A blocking issue prevents dependent detection and financial approval.",
    )
    explanation = models.TextField(help_text="Safe explanation. Never a whole source record.")
    chosen_source = models.ForeignKey(
        DataSource,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reconciliation_resolutions",
    )
    resolved_by = models.ForeignKey(
        "organizations.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reconciliation_issues_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    # Typed canonical subject. Exactly one is populated.
    customer = models.ForeignKey(
        "operations.CustomerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reconciliation_issues",
    )
    site = models.ForeignKey(
        "operations.Site",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reconciliation_issues",
    )
    contract = models.ForeignKey(
        "operations.Contract",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reconciliation_issues",
    )
    service_obligation = models.ForeignKey(
        "operations.ServiceObligation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reconciliation_issues",
    )
    work_order = models.ForeignKey(
        "operations.WorkOrder",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reconciliation_issues",
    )
    accounting_invoice = models.ForeignKey(
        "operations.AccountingInvoice",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reconciliation_issues",
    )
    accounting_payment = models.ForeignKey(
        "operations.AccountingPayment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reconciliation_issues",
    )

    class Meta:
        db_table = "ingestion_reconciliation_issue"
        constraints = [
            models.CheckConstraint(
                condition=_exactly_one_target(), name="ck_reconciliation_issue_one_subject"
            ),
            models.CheckConstraint(
                condition=Q(status="open")
                | (Q(resolved_by__isnull=False) & Q(resolved_at__isnull=False)),
                name="ck_reconciliation_resolution_attributed",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.entity_type}/{self.field_group} ({self.status})"

    @property
    def blocks_dependents(self) -> bool:
        return self.status == self.Status.OPEN and self.is_blocking

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "chosen_source", *TARGET_FIELDS)
        populated = [f for f in TARGET_FIELDS if getattr(self, f"{f}_id", None) is not None]
        if len(populated) != 1:
            raise ValidationError("A reconciliation issue must name exactly one subject.")
        if populated[0] != self.entity_type:
            raise ValidationError(
                {"entity_type": "The populated subject does not match the declared entity type."}
            )


class ImportBatch(TenantScopedModel):
    """One uploaded file and everything known about that observation.

    The uniqueness constraint is the idempotency contract (section 22.3, line 874).
    It deliberately includes `source_as_of_at` and `coverage_manifest_sha256` as well
    as the content hash: "The same empty accounting export at a later legitimate
    source-as-of time is a new observation; an exact replay of the same file plus
    observation/coverage manifest is not."
    """

    class Kind(models.TextChoices):
        """The seven mapped CSV contracts (section 27).

        Route B implements four. The other three are part of the vocabulary but have no
        validator, and a file declaring one is rejected rather than silently accepted.
        """

        SITES_CONTRACTS = "sites_contracts", "Sites and contracts"
        ENTITY_CROSSWALK = "entity_crosswalk", "Entity crosswalk"
        WORKERS_ELIGIBILITY = "workers_eligibility", "Workers and eligibility"
        SCHEDULED_SHIFTS = "scheduled_shifts", "Scheduled shifts"
        TIME_ENTRIES = "time_entries", "Time entries"
        WORK_ORDERS_SERVICE_EVENTS = "work_orders_service_events", "Work orders and service events"
        INVOICE_STATUS = "invoice_status", "Invoice status"

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        VALIDATING = "validating", "Validating"
        INVALID = "invalid", "Invalid"
        READY = "ready", "Ready to commit"
        COMMITTING = "committing", "Committing"
        COMMITTED = "committed", "Committed"
        FAILED = "failed", "Failed"

    class ObservationMode(models.TextChoices):
        FULL_SNAPSHOT = "full_snapshot", "Full snapshot"
        BOUNDED_SNAPSHOT = "bounded_snapshot", "Bounded snapshot"
        DELTA = "delta", "Delta"

    source = models.ForeignKey(DataSource, on_delete=models.PROTECT, related_name="import_batches")
    kind = models.CharField(max_length=32, choices=Kind)
    status = models.CharField(max_length=16, choices=Status, default=Status.UPLOADED)

    original_filename = models.CharField(
        max_length=255, help_text="Sanitized basename only; never a path."
    )
    content_sha256 = models.CharField(max_length=64)
    mapping_version = models.PositiveIntegerField(default=1)
    source_as_of_at = models.DateTimeField(help_text="When the source system produced this export.")
    observation_mode = models.CharField(max_length=24, choices=ObservationMode)
    source_watermark = models.CharField(
        max_length=200,
        blank=True,
        help_text="Opaque non-secret source cursor used only for ordering and replay explanation.",
    )
    coverage_manifest_sha256 = models.CharField(
        max_length=64, help_text="Hash of the normalized coverage declarations."
    )

    total_row_count = models.PositiveIntegerField(default=0)
    valid_row_count = models.PositiveIntegerField(default=0)
    invalid_row_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    unchanged_count = models.PositiveIntegerField(default=0)

    uploaded_by = models.ForeignKey(
        "organizations.User", on_delete=models.PROTECT, related_name="import_batches_uploaded"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    committed_by = models.ForeignKey(
        "organizations.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="import_batches_committed",
    )
    committed_at = models.DateTimeField(null=True, blank=True)

    failure_code = models.CharField(max_length=64, blank=True)
    failure_summary = models.CharField(
        max_length=500, blank=True, help_text="Safe summary. Never a raw row or stack trace."
    )

    class Meta:
        db_table = "ingestion_import_batch"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "organization",
                    "source",
                    "kind",
                    "content_sha256",
                    "mapping_version",
                    "source_as_of_at",
                    "coverage_manifest_sha256",
                ],
                name="uniq_import_batch_observation",
            ),
            models.CheckConstraint(
                condition=~Q(status="committed") | Q(committed_at__isnull=False),
                name="ck_import_batch_committed_has_timestamp",
            ),
        ]
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(
                fields=["organization", "kind", "-uploaded_at"], name="idx_batch_org_kind"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.original_filename}"

    @property
    def is_committed(self) -> bool:
        return self.status == self.Status.COMMITTED

    @property
    def is_snapshot(self) -> bool:
        return self.observation_mode in (
            self.ObservationMode.FULL_SNAPSHOT,
            self.ObservationMode.BOUNDED_SNAPSHOT,
        )

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "source")


class ImportCoverage(TenantScopedModel):
    """An explicit declaration of what a file completely covers.

    Section 22.3: "Negative evidence such as 'no time entry' or 'no invoice' is safe
    only when coverage is explicit." A `complete` row is valid only for a committed
    snapshot batch from an authoritative source; delta, partial, unknown, stale, or
    unresolved coverage can supply positive facts but can never prove absence.

    Intervals are half-open `[coverage_start_at, coverage_end_at)`.
    """

    class ScopeType(models.TextChoices):
        ORGANIZATION = "organization", "Whole organization"
        CUSTOMER = "customer", "One customer"
        SITE = "site", "One site"
        WORKER = "worker", "One worker"
        WORK_ORDER = "work_order", "One work order"
        SOURCE_LEDGER = "source_ledger", "The batch's own source ledger"

    class Completeness(models.TextChoices):
        COMPLETE = "complete", "Complete"
        PARTIAL = "partial", "Partial"
        UNKNOWN = "unknown", "Unknown"

    class DeclarationBasis(models.TextChoices):
        SOURCE_EXPORT_MANIFEST = "source_export_manifest", "Source export manifest"
        PARTNER_ATTESTATION = "partner_attestation", "Partner attestation"
        SYNTHETIC_FIXTURE = "synthetic_fixture", "Synthetic fixture"

    class QueryContract(models.TextChoices):
        """Allowlisted query semantics (section 22.3, line 884).

        "never let arbitrary user text define query semantics."
        """

        SCHEDULE_OVERLAP_V1 = "SCHEDULE_OVERLAP_V1", "Schedule overlap v1"
        TIME_ENTRY_OVERLAP_V1 = "TIME_ENTRY_OVERLAP_V1", "Time entry overlap v1"
        WORKER_AVAILABILITY_OVERLAP_V1 = (
            "WORKER_AVAILABILITY_OVERLAP_V1",
            "Worker availability overlap v1",
        )
        SERVICE_EVENT_CURRENT_STATE_V1 = (
            "SERVICE_EVENT_CURRENT_STATE_V1",
            "Service event current state v1",
        )
        ACCOUNTING_SERVICE_DATE_LEDGER_V1 = (
            "ACCOUNTING_SERVICE_DATE_LEDGER_V1",
            "Accounting service-date ledger v1",
        )

    import_batch = models.ForeignKey(
        ImportBatch, on_delete=models.CASCADE, related_name="coverage_declarations"
    )
    record_family = models.CharField(max_length=64)
    scope_type = models.CharField(max_length=24, choices=ScopeType)

    customer = models.ForeignKey(
        "operations.CustomerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="coverage_declarations",
    )
    site = models.ForeignKey(
        "operations.Site",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="coverage_declarations",
    )
    work_order = models.ForeignKey(
        "operations.WorkOrder",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="coverage_declarations",
    )

    coverage_start_at = models.DateTimeField()
    coverage_end_at = models.DateTimeField()
    query_contract_code = models.CharField(max_length=48, choices=QueryContract)
    query_contract_version = models.PositiveIntegerField(default=1)
    completeness = models.CharField(max_length=16, choices=Completeness)
    declaration_basis = models.CharField(max_length=32, choices=DeclarationBasis)
    declared_by = models.ForeignKey(
        "organizations.User", on_delete=models.PROTECT, related_name="coverage_declarations"
    )
    declared_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingestion_import_coverage"
        constraints = [
            models.CheckConstraint(
                condition=Q(coverage_end_at__gt=models.F("coverage_start_at")),
                name="ck_coverage_interval_ordered",
            ),
        ]
        ordering = ["record_family", "coverage_start_at"]

    def __str__(self) -> str:
        return f"{self.record_family} {self.completeness}"

    @property
    def proves_absence(self) -> bool:
        """Whether this declaration may support a negative-evidence query.

        Requires all four: complete, an authoritative source, a committed batch, and a
        snapshot observation mode. Any one missing yields insufficient coverage.
        """
        return (
            self.completeness == self.Completeness.COMPLETE
            and self.import_batch.source.is_authoritative
            and self.import_batch.is_committed
            and self.import_batch.is_snapshot
        )

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "import_batch", "customer", "site", "work_order")
        # Keyed by the plain stored value: scope_type is a CharField, not the enum.
        required_target_field: dict[str, str] = {
            ImportCoverage.ScopeType.CUSTOMER.value: "customer_id",
            ImportCoverage.ScopeType.SITE.value: "site_id",
            ImportCoverage.ScopeType.WORK_ORDER.value: "work_order_id",
        }
        target_field = required_target_field.get(str(self.scope_type))
        if target_field and getattr(self, target_field) is None:
            raise ValidationError(
                {"scope_type": f"A {self.scope_type} scope must name its target."}
            )


class ImportRow(TenantScopedModel):
    """One parsed row. Immutable after validation and never logged."""

    class Status(models.TextChoices):
        VALID = "valid", "Valid"
        INVALID = "invalid", "Invalid"
        COMMITTED = "committed", "Committed"
        UNCHANGED = "unchanged", "Unchanged"

    import_batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField(help_text="One-based, matching the source file.")
    raw_data = models.JSONField(help_text="Parsed key/value pairs. Never logged or exported.")
    normalized_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status)
    error_codes = models.JSONField(default=list, blank=True)
    target_model = models.CharField(max_length=64, blank=True)
    target_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "ingestion_import_row"
        constraints = [
            models.UniqueConstraint(
                fields=["import_batch", "row_number"], name="uniq_import_row_number"
            ),
            models.CheckConstraint(condition=Q(row_number__gte=1), name="ck_import_row_one_based"),
        ]
        ordering = ["import_batch", "row_number"]

    def __str__(self) -> str:
        return f"row {self.row_number}"


class SourceRecordVersion(TenantScopedModel):
    """Append-only history of what a source said about one record.

    Section 22.3: "Append-only; never update an old version." The application provides
    no update path; a changed import inserts a new version pointing at its predecessor.
    """

    source = models.ForeignKey(DataSource, on_delete=models.PROTECT, related_name="record_versions")
    record_type = models.CharField(max_length=48)
    external_id = models.CharField(max_length=128)
    version_hash = models.CharField(max_length=64)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    import_batch = models.ForeignKey(
        ImportBatch, on_delete=models.PROTECT, related_name="record_versions"
    )
    canonical_data = models.JSONField(
        help_text="Minimum normalized snapshot required to reproduce a detector decision."
    )
    supersedes = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="superseded_by"
    )

    class Meta:
        db_table = "ingestion_source_record_version"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "source", "record_type", "external_id", "version_hash"],
                name="uniq_source_record_version",
            )
        ]
        ordering = ["-imported_at"]
        indexes = [
            models.Index(
                fields=["organization", "record_type", "external_id"],
                name="idx_srv_org_type_extid",
            )
        ]

    def __str__(self) -> str:
        return f"{self.record_type}:{self.external_id}@{self.version_hash[:8]}"

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "source", "import_batch")


class ReconciliationRun(TenantScopedModel):
    """An immutable evaluation manifest.

    Section 22.3: the transition to `ready` happens atomically only when all required
    batches are committed, their identities are resolved, blocking reconciliation issues
    are absent, and the required coverage is present.

    **Phase 3 stops here.** No `DetectorDispatchIntent` is created and nothing is
    published; detector handlers do not exist yet, so the seam is tested as
    readiness-only (line 2404).
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        WAITING_INPUTS = "waiting_inputs", "Waiting for inputs"
        READY = "ready", "Ready"
        ENQUEUED = "enqueued", "Enqueued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    run_key = models.CharField(max_length=128)
    as_of = models.DateTimeField()
    input_manifest_sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=24, choices=Status, default=Status.DRAFT)
    became_ready_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ingestion_reconciliation_run"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "run_key"], name="uniq_reconciliation_run_key"
            ),
            models.CheckConstraint(
                condition=~Q(status="ready") | Q(became_ready_at__isnull=False),
                name="ck_reconciliation_ready_has_timestamp",
            ),
        ]
        ordering = ["-as_of"]

    def __str__(self) -> str:
        return f"{self.run_key} ({self.status})"

    @property
    def is_ready(self) -> bool:
        return self.status == self.Status.READY


class ReconciliationRunInput(TenantScopedModel):
    """One required domain in a run's immutable input manifest.

    Section 22.3: the manifest "lists each required domain, committed ImportBatch,
    accepted source watermark, and exact ImportCoverage rows used by each selected
    detector."
    """

    reconciliation_run = models.ForeignKey(
        ReconciliationRun, on_delete=models.CASCADE, related_name="inputs"
    )
    domain = models.CharField(max_length=32, choices=DataSource.Domain)
    import_batch = models.ForeignKey(
        ImportBatch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reconciliation_inputs",
        help_text="Null while the run is still waiting for this domain.",
    )
    accepted_watermark = models.CharField(max_length=200, blank=True)
    coverage_declarations = models.ManyToManyField(
        ImportCoverage, blank=True, related_name="reconciliation_inputs"
    )

    class Meta:
        db_table = "ingestion_reconciliation_run_input"
        constraints = [
            models.UniqueConstraint(
                fields=["reconciliation_run", "domain"], name="uniq_run_input_domain"
            )
        ]
        ordering = ["reconciliation_run", "domain"]

    def __str__(self) -> str:
        return f"{self.domain}"

    @property
    def is_satisfied(self) -> bool:
        """A domain is satisfied only by a batch that actually committed."""
        batch = self.import_batch
        return batch is not None and batch.is_committed

    def clean(self) -> None:
        super().clean()
        assert_same_organization(self, "reconciliation_run", "import_batch")
