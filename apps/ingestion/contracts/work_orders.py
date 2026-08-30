"""`work_orders_service_events.csv` — section 28.6, work-order family only.

One file carries four `record_type` values. The Route B matrix authorizes "work-order
rows from work_orders_service_events" (line 2297) and nothing else, so the three
quality record types are **rejected with a row error** rather than accepted and ignored.
Silently skipping them would look like a successful import that lost data.
"""

from __future__ import annotations

from apps.ingestion.contracts.base import Column, Contract, Requirement, require_together
from apps.ingestion.errors import ErrorCode, RowError

RECORD_TYPES = ("work_order", "inspection_failure", "service_deficiency", "client_service_call")
SUPPORTED_RECORD_TYPES = ("work_order",)
WORK_ORDER_STATUSES = ("open", "in_progress", "completed", "cancelled", "void")
BILLING_BASES = (
    "included",
    "fixed_work_order",
    "hourly_actual",
    "hourly_scheduled",
    "manual_review",
)


def _reject_unsupported_record_type(values: dict[str, object]) -> list[RowError]:
    record_type = values.get("record_type")
    if record_type and record_type not in SUPPORTED_RECORD_TYPES:
        # Quality record types belong to Journey C, which is unbuilt under Route B.
        return [RowError(ErrorCode.INVALID_ENUM, column="record_type")]
    return []


def _require_completion_evidence(values: dict[str, object]) -> list[RowError]:
    if values.get("source_status") == "completed" and values.get("completed_at") is None:
        return [RowError(ErrorCode.BLANK_REQUIRED_VALUE, column="completed_at")]
    return []


# NOTE: absence of authorization evidence is deliberately NOT an import error.
# Section 28.6 requires `authorization_reference` only "when authorization is required
# AND obtained". A work order that needed authorization and never received it is a real
# source state, and it is the negative control the demo depends on: section 24.2
# condition 5 makes the DETECTOR refuse to treat it as billable. Rejecting the row here
# would discard the very evidence that check needs.


def _require_supported_billing_basis(values: dict[str, object]) -> list[RowError]:
    basis = values.get("billing_basis")
    if basis and basis not in BILLING_BASES:
        return [RowError(ErrorCode.UNSUPPORTED_BILLING_BASIS, column="billing_basis")]
    return []


CONTRACT = Contract(
    kind="work_orders_service_events",
    columns=(
        Column("source_system"),
        Column("record_type", choices=RECORD_TYPES),
        Column("record_external_id"),
        Column("customer_source_system"),
        Column("customer_external_id"),
        Column("site_source_system"),
        Column("site_external_id"),
        Column("contract_source_system"),
        Column("contract_external_id"),
        Column("service_obligation_source_system", Requirement.OPTIONAL),
        Column("service_obligation_external_id", Requirement.OPTIONAL),
        Column("summary", max_length=500),
        Column("severity", Requirement.CONDITIONAL, meaning="Required for a quality record."),
        Column("occurred_at", kind="timestamp"),
        Column("received_at", Requirement.CONDITIONAL, kind="timestamp"),
        Column("scheduled_at", Requirement.OPTIONAL, kind="timestamp"),
        Column("completed_at", Requirement.CONDITIONAL, kind="timestamp"),
        Column("source_status", choices=WORK_ORDER_STATUSES),
        Column("billable", Requirement.CONDITIONAL, kind="boolean"),
        Column("authorization_required", Requirement.CONDITIONAL, kind="boolean"),
        Column("authorization_reference", Requirement.CONDITIONAL),
        Column("authorized_at", Requirement.CONDITIONAL, kind="timestamp"),
        Column("billing_basis", Requirement.CONDITIONAL, choices=BILLING_BASES),
        Column("approved_fixed_amount", Requirement.OPTIONAL, kind="decimal"),
        Column("approved_hours", Requirement.OPTIONAL, kind="decimal"),
        Column("bill_rate", Requirement.OPTIONAL, kind="decimal"),
        Column("response_due_at", Requirement.OPTIONAL, kind="timestamp", unused_in_route_b=True),
        Column("correction_due_at", Requirement.OPTIONAL, kind="timestamp", unused_in_route_b=True),
        Column("corrected_at", Requirement.OPTIONAL, kind="timestamp", unused_in_route_b=True),
        Column("source_updated_at", Requirement.OPTIONAL, kind="timestamp"),
        Column("source_as_of_at", kind="timestamp"),
    ),
    row_validators=(
        _reject_unsupported_record_type,
        _require_completion_evidence,
        _require_supported_billing_basis,
        require_together("service_obligation_external_id", "service_obligation_source_system"),
    ),
)
