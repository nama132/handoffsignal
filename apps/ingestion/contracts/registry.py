"""Which CSV contracts exist in this phase.

Route B implements four of the seven. Asking for one of the other three raises rather
than returning an empty contract, so an unimplemented importer can never look like a
successful no-op import (Phase 3 gate, line 2540: "omitted types have no placeholder
implementation").
"""

from __future__ import annotations

from apps.ingestion.contracts import (
    entity_crosswalk,
    invoice_status,
    sites_contracts,
    work_orders,
)
from apps.ingestion.contracts.base import Contract

CONTRACTS: dict[str, Contract] = {
    sites_contracts.CONTRACT.kind: sites_contracts.CONTRACT,
    entity_crosswalk.CONTRACT.kind: entity_crosswalk.CONTRACT,
    work_orders.CONTRACT.kind: work_orders.CONTRACT,
    invoice_status.CONTRACT.kind: invoice_status.CONTRACT,
}

#: Declared in the vocabulary but not implemented under Route B.
UNIMPLEMENTED_KINDS: frozenset[str] = frozenset(
    {"workers_eligibility", "scheduled_shifts", "time_entries"}
)


class ContractNotImplemented(Exception):
    """Raised for a CSV kind that Route B deliberately does not implement."""


def get_contract(kind: str) -> Contract:
    contract = CONTRACTS.get(kind)
    if contract is None:
        raise ContractNotImplemented(
            f"{kind!r} has no validator in this phase. Route B implements {sorted(CONTRACTS)} only."
        )
    return contract
