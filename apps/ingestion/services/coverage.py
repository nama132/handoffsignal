"""Coverage declarations and their manifest hash.

Section 27 step 6: the user must declare observation mode and bounded coverage
scope/interval/completeness on the import form; it is shown in preview and requires an
explicit commit. "Never infer completeness from filename, row count, or freshness."
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass

from apps.ingestion.errors import ErrorCode, RowError
from apps.ingestion.models import DataSource, ImportBatch, ImportCoverage

#: Which query contracts each record family may legitimately declare. Section 22.3
#: allowlists the semantics; a family may not borrow another's contract.
ALLOWED_QUERY_CONTRACTS: dict[str, tuple[str, ...]] = {
    "work_order": (ImportCoverage.QueryContract.SERVICE_EVENT_CURRENT_STATE_V1,),
    "accounting_invoice": (ImportCoverage.QueryContract.ACCOUNTING_SERVICE_DATE_LEDGER_V1,),
    "accounting_payment": (ImportCoverage.QueryContract.ACCOUNTING_SERVICE_DATE_LEDGER_V1,),
    "contract_scope": (),
    "entity_crosswalk": (),
}

#: Record families each CSV kind declares coverage for.
RECORD_FAMILIES: dict[str, tuple[str, ...]] = {
    "sites_contracts": ("contract_scope",),
    "entity_crosswalk": ("entity_crosswalk",),
    "work_orders_service_events": ("work_order",),
    "invoice_status": ("accounting_invoice",),
}


@dataclass(frozen=True)
class CoverageDeclaration:
    """One declared coverage row, before it is persisted."""

    record_family: str
    scope_type: str
    coverage_start_at: dt.datetime
    coverage_end_at: dt.datetime
    query_contract_code: str
    query_contract_version: int
    completeness: str
    declaration_basis: str
    customer_id: str | None = None
    site_id: str | None = None
    work_order_id: str | None = None

    def normalized(self) -> dict[str, object]:
        """Stable representation used for the manifest hash."""
        return {
            "record_family": self.record_family,
            "scope_type": self.scope_type,
            "coverage_start_at": self.coverage_start_at.astimezone(dt.UTC).isoformat(),
            "coverage_end_at": self.coverage_end_at.astimezone(dt.UTC).isoformat(),
            "query_contract_code": self.query_contract_code,
            "query_contract_version": self.query_contract_version,
            "completeness": self.completeness,
            "declaration_basis": self.declaration_basis,
            "customer_id": self.customer_id,
            "site_id": self.site_id,
            "work_order_id": self.work_order_id,
        }


def manifest_hash(declarations: list[CoverageDeclaration]) -> str:
    """Hash the normalized declarations.

    Part of the ImportBatch idempotency key, so the same bytes declared with different
    coverage are a different observation rather than a duplicate.
    """
    payload = json.dumps(
        sorted(
            (d.normalized() for d in declarations),
            key=lambda item: json.dumps(item, sort_keys=True),
        ),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_declarations(
    kind: str, source: DataSource, declarations: list[CoverageDeclaration]
) -> list[RowError]:
    """Check declarations against the allowlist and the source's authority."""
    errors: list[RowError] = []
    expected_families = RECORD_FAMILIES.get(kind, ())

    if not declarations:
        return [RowError(ErrorCode.COVERAGE_MANIFEST_MISSING)]

    for declaration in declarations:
        if declaration.record_family not in expected_families:
            errors.append(RowError(ErrorCode.COVERAGE_SCOPE_INVALID, column="record_family"))
            continue

        if declaration.coverage_end_at <= declaration.coverage_start_at:
            errors.append(RowError(ErrorCode.COVERAGE_INTERVAL_INVALID, column="coverage_end_at"))

        allowed = ALLOWED_QUERY_CONTRACTS.get(declaration.record_family, ())
        if allowed and declaration.query_contract_code not in allowed:
            errors.append(
                RowError(ErrorCode.COVERAGE_QUERY_CONTRACT_INVALID, column="query_contract_code")
            )

        if (
            declaration.scope_type == ImportCoverage.ScopeType.CUSTOMER
            and not declaration.customer_id
        ):
            errors.append(RowError(ErrorCode.COVERAGE_SCOPE_INVALID, column="scope_type"))
        if declaration.scope_type == ImportCoverage.ScopeType.SITE and not declaration.site_id:
            errors.append(RowError(ErrorCode.COVERAGE_SCOPE_INVALID, column="scope_type"))

        # Only an authoritative source may claim completeness: a non-authoritative feed
        # cannot prove that something is absent from the system of record.
        if (
            declaration.completeness == ImportCoverage.Completeness.COMPLETE
            and not source.is_authoritative
        ):
            errors.append(RowError(ErrorCode.COVERAGE_NOT_AUTHORITATIVE, column="completeness"))

    return errors


def persist_declarations(
    batch: ImportBatch, declarations: list[CoverageDeclaration], declared_by
) -> list[ImportCoverage]:
    rows = []
    for declaration in declarations:
        rows.append(
            ImportCoverage.objects.create(
                organization=batch.organization,
                import_batch=batch,
                record_family=declaration.record_family,
                scope_type=declaration.scope_type,
                customer_id=declaration.customer_id,
                site_id=declaration.site_id,
                work_order_id=declaration.work_order_id,
                coverage_start_at=declaration.coverage_start_at,
                coverage_end_at=declaration.coverage_end_at,
                query_contract_code=declaration.query_contract_code,
                query_contract_version=declaration.query_contract_version,
                completeness=declaration.completeness,
                declaration_basis=declaration.declaration_basis,
                declared_by=declared_by,
            )
        )
    return rows
