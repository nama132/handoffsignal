"""`entity_crosswalk.csv` — section 28.2.

"This file proves the cross-system wedge. It maps an alias from one source namespace to
a canonical entity already established by another source. No fuzzy match may
auto-confirm."
"""

from __future__ import annotations

from apps.ingestion.contracts.base import Column, Contract, Requirement

ENTITY_TYPES = (
    "customer",
    "site",
    "contract",
    "service_obligation",
    "worker",
    "availability_window",
    "shift",
    "time_entry",
    "work_order",
    "quality_event",
    "accounting_invoice",
    "accounting_payment",
)

#: Entity types whose canonical models exist under Route B. A crosswalk row naming one
#: of the others is rejected as an unknown parent reference rather than silently stored,
#: because there is nothing for it to resolve to.
ROUTE_B_ENTITY_TYPES = (
    "customer",
    "site",
    "contract",
    "service_obligation",
    "work_order",
    "accounting_invoice",
    "accounting_payment",
)

MATCH_METHODS = ("partner_canonical_key", "manual", "deterministic_exact")

CONTRACT = Contract(
    kind="entity_crosswalk",
    columns=(
        Column("entity_type", choices=ENTITY_TYPES),
        Column("alias_source_system", meaning="Source containing the alternate identifier."),
        Column("alias_external_id"),
        Column("canonical_source_system", meaning="Source of an existing confirmed reference."),
        Column("canonical_external_id"),
        Column(
            "match_method", choices=MATCH_METHODS, meaning="Fuzzy matching may never auto-confirm."
        ),
        Column(
            "approval_reference",
            Requirement.CONDITIONAL,
            meaning="Required for a manual or partner-approved mapping.",
        ),
        Column("mapping_note", Requirement.OPTIONAL, max_length=500),
    ),
)
