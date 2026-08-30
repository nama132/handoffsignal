"""`sites_contracts.csv` — section 28.1.

One row per contract-site-service-obligation and optional required qualification.

Route B note: this contract carries fourteen attendance- and quality-only columns
(grace periods, deficiency SLAs, weekly-hours thresholds, workweek boundaries,
availability policy, client notification, and the qualification triple). Their target
models — SiteOperationalRule, SiteRequirement, QualificationType — are deliberately not
built. The columns are still declared and validated, because the schema is the schema
and a partner's export will contain them; they are marked `unused_in_route_b` and
persisted nowhere. Evidence expansion step E1 gives them a home if Journeys A or C are
approved.
"""

from __future__ import annotations

from apps.ingestion.contracts.base import Column, Contract, Requirement

SITE_TYPES = ("office", "retail", "light_industrial", "other")
CONTRACT_STATUSES = ("active", "inactive", "ended")
SCOPE_KINDS = ("base_recurring", "authorized_extra", "periodic", "corrective")
BILLING_BASES = (
    "included",
    "fixed_work_order",
    "hourly_actual",
    "hourly_scheduled",
    "manual_review",
)
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
AVAILABILITY_POLICIES = ("explicit_available_required", "conflicts_only")
REQUIREMENT_KINDS = ("training", "badge", "role", "access")

CONTRACT = Contract(
    kind="sites_contracts",
    columns=(
        Column("source_system", meaning="Configured organization-unique source namespace."),
        Column("customer_external_id", meaning="Stable within tenant and source."),
        Column("customer_name", max_length=200),
        Column("site_external_id"),
        Column("site_name", max_length=200),
        Column("site_type", choices=SITE_TYPES),
        Column("site_timezone", meaning="Valid IANA timezone."),
        Column("region_code", Requirement.OPTIONAL, meaning="Coarse region, never an address."),
        Column("contract_external_id"),
        Column("contract_status", choices=CONTRACT_STATUSES),
        Column("starts_on", kind="date"),
        Column("ends_on", Requirement.OPTIONAL, kind="date"),
        Column("service_obligation_external_id"),
        Column("service_obligation_label", max_length=200),
        Column("service_type"),
        Column("scope_kind", choices=SCOPE_KINDS),
        Column("service_window_start", kind="time", meaning="Site-local time."),
        Column("service_window_end", kind="time", meaning="Site-local; overnight supported."),
        Column("service_weekdays", meaning="Explicit controlled list, comma separated."),
        Column("role_code"),
        Column("required_coverage_count", kind="integer"),
        Column("substitution_required_when_below_count", kind="boolean"),
        Column("billing_basis", choices=BILLING_BASES),
        Column("default_bill_rate", Requirement.CONDITIONAL, kind="decimal"),
        Column("currency", choices=("USD",)),
        Column("extra_work_requires_authorization", kind="boolean"),
        Column("uninvoiced_delay_days", kind="integer"),
        # --- Journey A / C columns: validated, never persisted under Route B ---
        Column("no_show_grace_minutes", kind="integer", unused_in_route_b=True),
        Column("replacement_buffer_minutes", kind="integer", unused_in_route_b=True),
        Column("attendance_escalation_minutes", kind="integer", unused_in_route_b=True),
        Column("deficiency_response_minutes", kind="integer", unused_in_route_b=True),
        Column("deficiency_correction_minutes", kind="integer", unused_in_route_b=True),
        Column("weekly_hours_warning_threshold", kind="decimal", unused_in_route_b=True),
        Column(
            "weekly_hours_hard_limit", Requirement.OPTIONAL, kind="decimal", unused_in_route_b=True
        ),
        Column("workweek_start_weekday", choices=WEEKDAYS, unused_in_route_b=True),
        Column("workweek_start_local_time", kind="time", unused_in_route_b=True),
        Column(
            "availability_evidence_policy", choices=AVAILABILITY_POLICIES, unused_in_route_b=True
        ),
        Column("client_notification_required", kind="boolean", unused_in_route_b=True),
        Column("required_qualification_code", Requirement.OPTIONAL, unused_in_route_b=True),
        Column("required_program_version", Requirement.CONDITIONAL, unused_in_route_b=True),
        Column(
            "requirement_kind",
            Requirement.CONDITIONAL,
            choices=REQUIREMENT_KINDS,
            unused_in_route_b=True,
        ),
        Column(
            "requirement_effective_from",
            Requirement.CONDITIONAL,
            kind="date",
            unused_in_route_b=True,
        ),
        Column(
            "requirement_effective_to", Requirement.OPTIONAL, kind="date", unused_in_route_b=True
        ),
    ),
)
