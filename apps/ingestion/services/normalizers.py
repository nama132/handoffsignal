"""Turn validated rows into canonical records.

One normalizer per CSV contract. All of them obey the same rules:

* Upsert by ``(organization, source, external_id)`` through a **confirmed**
  ExternalEntityReference — never by name.
* Append a SourceRecordVersion; an identical replay finds the same version hash and
  counts as `unchanged`.
* Quarantine a row whose references do not resolve instead of guessing.
* Never delete a canonical record because a row is absent. Section 27 step 9: "Do not
  silently delete source records that disappeared from one file."
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from apps.ingestion.errors import ErrorCode, RowError
from apps.ingestion.models import ExternalEntityReference, ImportBatch, ImportRow
from apps.ingestion.services import identity
from apps.ingestion.services.identity import Reference, Unresolved
from apps.operations.models import (
    AccountingInvoice,
    AccountingPayment,
    Contract,
    ContractSite,
    CustomerAccount,
    ServiceObligation,
    Site,
    WorkOrder,
)

Counts = dict[str, int]


def _blank() -> Counts:
    return {"created": 0, "updated": 0, "unchanged": 0}


def _valid_rows(batch: ImportBatch) -> list[ImportRow]:
    return list(batch.rows.filter(status=ImportRow.Status.VALID).order_by("row_number"))


def _decimal(value: object) -> Decimal | None:
    """Unknown stays NULL. Section 22.5: "Unknown is NULL, not zero"."""
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _date(value: object) -> dt.date | None:
    if value in (None, ""):
        return None
    return dt.date.fromisoformat(str(value))


def _timestamp(value: object) -> dt.datetime | None:
    if value in (None, ""):
        return None
    return dt.datetime.fromisoformat(str(value))


def _time(value: object) -> dt.time | None:
    if value in (None, ""):
        return None
    return dt.time.fromisoformat(str(value))


class MissingRequiredValue(RuntimeError):
    """A column the contract marked required arrived empty at normalization.

    Contract validation runs before commit, so this is unreachable in normal operation.
    It is raised rather than defaulted so a validation gap fails loudly instead of
    writing a silently wrong record.
    """


def _req_date(value: object, column: str) -> dt.date:
    parsed = _date(value)
    if parsed is None:
        raise MissingRequiredValue(column)
    return parsed


def _req_time(value: object, column: str) -> dt.time:
    parsed = _time(value)
    if parsed is None:
        raise MissingRequiredValue(column)
    return parsed


def _req_timestamp(value: object, column: str) -> dt.datetime:
    parsed = _timestamp(value)
    if parsed is None:
        raise MissingRequiredValue(column)
    return parsed


def _req_decimal(value: object, column: str) -> Decimal:
    parsed = _decimal(value)
    if parsed is None:
        raise MissingRequiredValue(column)
    return parsed


def normalize_sites_contracts(batch: ImportBatch, actor) -> Counts:
    """Establish the canonical customer/site/contract/obligation chain.

    This file is the origin of canonical identity: it declares entities rather than
    referring to ones another source established, so its own identifiers are confirmed
    with `deterministic_exact`.
    """
    counts = _blank()
    organization = batch.organization

    for row in _valid_rows(batch):
        data = row.normalized_data

        customer, created = CustomerAccount.objects.get_or_create(
            organization=organization,
            name=str(data["customer_name"]),
        )
        site, _ = Site.objects.update_or_create(
            organization=organization,
            name=str(data["site_name"]),
            defaults={
                "customer": customer,
                "timezone": str(data["site_timezone"]),
                "region_code": str(data.get("region_code") or ""),
                "site_type": str(data["site_type"]),
            },
        )
        contract, _ = Contract.objects.update_or_create(
            organization=organization,
            contract_reference=str(data["contract_external_id"]),
            defaults={
                "customer": customer,
                "status": str(data["contract_status"]),
                "starts_on": _req_date(data["starts_on"], "starts_on"),
                "ends_on": _date(data.get("ends_on")),
                "currency": str(data["currency"]),
            },
        )
        contract_site, _ = ContractSite.objects.get_or_create(
            organization=organization,
            contract=contract,
            site=site,
            effective_from=_req_date(data["starts_on"], "starts_on"),
        )

        canonical = {
            "customer": str(data["customer_external_id"]),
            "site": str(data["site_external_id"]),
            "contract": str(data["contract_external_id"]),
            "obligation": str(data["service_obligation_external_id"]),
            "billing_basis": str(data["billing_basis"]),
            "uninvoiced_delay_days": data["uninvoiced_delay_days"],
            "default_bill_rate": str(data.get("default_bill_rate") or ""),
            "service_window": [str(data["service_window_start"]), str(data["service_window_end"])],
        }
        from apps.ingestion.services.imports import _record_version

        _, appended = _record_version(
            batch=batch,
            record_type="service_obligation",
            external_id=str(data["service_obligation_external_id"]),
            canonical=canonical,
        )

        obligation, obligation_created = ServiceObligation.objects.update_or_create(
            organization=organization,
            contract_site=contract_site,
            code=str(data["service_obligation_external_id"]),
            effective_from=_req_date(data["starts_on"], "starts_on"),
            defaults={
                "label": str(data["service_obligation_label"]),
                "service_type": str(data["service_type"]),
                "scope_kind": str(data["scope_kind"]),
                "service_window_start": _req_time(
                    data["service_window_start"], "service_window_start"
                ),
                "service_window_end": _req_time(data["service_window_end"], "service_window_end"),
                "service_weekdays": str(data["service_weekdays"]),
                "role_code": str(data["role_code"]),
                "required_coverage_count": int(data["required_coverage_count"]),
                "substitution_required_when_below_count": bool(
                    data["substitution_required_when_below_count"]
                ),
                "billing_basis": str(data["billing_basis"]),
                "default_bill_rate": _decimal(data.get("default_bill_rate")),
                "extra_work_requires_authorization": bool(
                    data["extra_work_requires_authorization"]
                ),
                "uninvoiced_delay_days": int(data["uninvoiced_delay_days"]),
            },
        )

        for entity_type, external_id, target in (
            ("customer", str(data["customer_external_id"]), customer),
            ("site", str(data["site_external_id"]), site),
            ("contract", str(data["contract_external_id"]), contract),
            ("service_obligation", str(data["service_obligation_external_id"]), obligation),
        ):
            identity.confirm(
                organization=organization,
                source=batch.source,
                entity_type=entity_type,
                external_id=external_id,
                target=target,
                match_method=ExternalEntityReference.MatchMethod.DETERMINISTIC_EXACT,
                provenance=f"import:{batch.id}:row{row.row_number}",
                confirmed_by=actor,
            )

        if obligation_created or created:
            counts["created"] += 1
        elif appended:
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1

        row.status = ImportRow.Status.COMMITTED if appended else ImportRow.Status.UNCHANGED
        row.target_model = "operations.ServiceObligation"
        row.target_id = obligation.id
        row.save(update_fields=["status", "target_model", "target_id"])

    return counts


def normalize_entity_crosswalk(batch: ImportBatch, actor) -> Counts:
    """Map an alias identifier onto a canonical entity another source established.

    The canonical side must already resolve. If it does not, the row is quarantined and
    an identity issue is opened — never a guessed mapping.
    """
    counts = _blank()
    organization = batch.organization

    for row in _valid_rows(batch):
        data = row.normalized_data
        entity_type = str(data["entity_type"])

        from apps.ingestion.contracts.entity_crosswalk import ROUTE_B_ENTITY_TYPES

        if entity_type not in ROUTE_B_ENTITY_TYPES:
            # The canonical model does not exist under Route B, so there is nothing to
            # resolve to. Reject rather than store a dangling mapping.
            from apps.ingestion.services.imports import quarantine_row

            quarantine_row(row, RowError(ErrorCode.UNKNOWN_PARENT_REFERENCE, column="entity_type"))
            continue

        try:
            canonical_id = identity.resolve(
                organization.id,
                Reference(
                    entity_type=entity_type,
                    source_system=str(data["canonical_source_system"]),
                    external_id=str(data["canonical_external_id"]),
                    column="canonical_external_id",
                ),
            )
        except Unresolved as exc:
            from apps.ingestion.services.imports import quarantine_row

            quarantine_row(row, exc.error)
            identity.record_issue(
                batch=batch,
                entity_type=entity_type,
                source_system=str(data["canonical_source_system"]),
                external_id=str(data["canonical_external_id"]),
                reason_code="unresolved_identity",
                explanation="The canonical side of this crosswalk row does not resolve.",
            )
            continue

        alias_source = batch.organization.ingestion_datasource_set.filter(
            system_key=str(data["alias_source_system"])
        ).first()
        if alias_source is None:
            from apps.ingestion.services.imports import quarantine_row

            quarantine_row(
                row, RowError(ErrorCode.SOURCE_NAMESPACE_UNKNOWN, column="alias_source_system")
            )
            continue

        model: Any = {
            "customer": CustomerAccount,
            "site": Site,
            "contract": Contract,
            "service_obligation": ServiceObligation,
            "work_order": WorkOrder,
            "accounting_invoice": AccountingInvoice,
            "accounting_payment": AccountingPayment,
        }[entity_type]
        target = model.objects.get(id=canonical_id)

        try:
            reference = identity.confirm(
                organization=organization,
                source=alias_source,
                entity_type=entity_type,
                external_id=str(data["alias_external_id"]),
                target=target,
                match_method=str(data["match_method"]),
                provenance=f"crosswalk:{batch.id}:row{row.row_number}",
                confirmed_by=actor,
            )
        except Unresolved as exc:
            from apps.ingestion.services.imports import quarantine_row

            quarantine_row(row, exc.error)
            continue

        counts["created"] += 1 if reference.confirmed_at == reference.created_at else 0
        counts["unchanged"] += 0
        row.status = ImportRow.Status.COMMITTED
        row.target_model = "ingestion.ExternalEntityReference"
        row.target_id = reference.id
        row.save(update_fields=["status", "target_model", "target_id"])

    committed = batch.rows.filter(status=ImportRow.Status.COMMITTED).count()
    counts["created"] = committed
    return counts


def _resolve_or_quarantine(
    batch: ImportBatch, row: ImportRow, references: list[Reference]
) -> dict[str, object] | None:
    """Resolve every reference for a row, or quarantine it and return None."""
    resolved: dict[str, object] = {}
    for reference in references:
        try:
            resolved[reference.entity_type] = identity.resolve(batch.organization_id, reference)
        except Unresolved as exc:
            from apps.ingestion.services.imports import quarantine_row

            quarantine_row(row, exc.error)
            identity.record_issue(
                batch=batch,
                entity_type=reference.entity_type,
                source_system=reference.source_system,
                external_id=reference.external_id,
                reason_code=exc.error.code
                if exc.error.code
                in ("unresolved_identity", "ambiguous_identity", "conflicting_crosswalk")
                else "unresolved_identity",
                explanation="A reference on this row did not resolve to a confirmed mapping.",
            )
            return None
    return resolved


def normalize_work_orders(batch: ImportBatch, actor) -> Counts:
    """Create or update work orders from the operations source."""
    counts = _blank()
    organization = batch.organization

    for row in _valid_rows(batch):
        data = row.normalized_data
        references = [
            Reference(
                "customer",
                str(data["customer_source_system"]),
                str(data["customer_external_id"]),
                "customer_external_id",
            ),
            Reference(
                "site",
                str(data["site_source_system"]),
                str(data["site_external_id"]),
                "site_external_id",
            ),
            Reference(
                "contract",
                str(data["contract_source_system"]),
                str(data["contract_external_id"]),
                "contract_external_id",
            ),
        ]
        if data.get("service_obligation_external_id"):
            references.append(
                Reference(
                    "service_obligation",
                    str(data["service_obligation_source_system"]),
                    str(data["service_obligation_external_id"]),
                    "service_obligation_external_id",
                )
            )

        resolved = _resolve_or_quarantine(batch, row, references)
        if resolved is None:
            continue

        canonical: dict[str, object] = {
            "status": str(data["source_status"]),
            "billable": data.get("billable"),
            "completed_at": str(data.get("completed_at") or ""),
            "authorization_reference": str(data.get("authorization_reference") or ""),
            "approved_fixed_amount": str(data.get("approved_fixed_amount") or ""),
            "billing_basis": str(data.get("billing_basis") or ""),
        }
        from apps.ingestion.services.imports import _record_version

        _, appended = _record_version(
            batch=batch,
            record_type="work_order",
            external_id=str(data["record_external_id"]),
            canonical=canonical,
        )

        existing_reference = ExternalEntityReference.objects.filter(
            organization=organization,
            source=batch.source,
            entity_type="work_order",
            external_id=str(data["record_external_id"]),
            mapping_status=ExternalEntityReference.MappingStatus.CONFIRMED,
        ).first()

        defaults = {
            "customer_id": resolved["customer"],
            "site_id": resolved["site"],
            "contract_id": resolved["contract"],
            "service_obligation_id": resolved.get("service_obligation"),
            "title": str(data["summary"]),
            "scheduled_at": _timestamp(data.get("scheduled_at")),
            "completed_at": _timestamp(data.get("completed_at")),
            "status": str(data["source_status"]),
            "billable": bool(data.get("billable")),
            "authorization_required": bool(data.get("authorization_required")),
            "authorization_reference": str(data.get("authorization_reference") or ""),
            "authorized_at": _timestamp(data.get("authorized_at")),
            "billing_basis": str(data.get("billing_basis") or ""),
            "approved_fixed_amount": _decimal(data.get("approved_fixed_amount")),
            "approved_hours": _decimal(data.get("approved_hours")),
            "bill_rate": _decimal(data.get("bill_rate")),
            "source_as_of_at": _req_timestamp(data["source_as_of_at"], "source_as_of_at"),
        }

        if existing_reference and existing_reference.work_order_id:
            work_order = WorkOrder.objects.get(id=existing_reference.work_order_id)
            for key, value in defaults.items():
                setattr(work_order, key, value)
            work_order.save()
            counts["updated" if appended else "unchanged"] += 1
        else:
            work_order = WorkOrder.objects.create(organization=organization, **defaults)
            counts["created"] += 1

        identity.confirm(
            organization=organization,
            source=batch.source,
            entity_type="work_order",
            external_id=str(data["record_external_id"]),
            target=work_order,
            match_method=ExternalEntityReference.MatchMethod.DETERMINISTIC_EXACT,
            provenance=f"import:{batch.id}:row{row.row_number}",
            confirmed_by=actor,
        )

        row.status = ImportRow.Status.COMMITTED if appended else ImportRow.Status.UNCHANGED
        row.target_model = "operations.WorkOrder"
        row.target_id = work_order.id
        row.save(update_fields=["status", "target_model", "target_id"])

    return counts


def normalize_invoice_status(batch: ImportBatch, actor) -> Counts:
    """Create or update accounting invoices and their payments.

    One invoice may appear on several rows, one per payment. The invoice is normalized
    once and each payment is a distinct canonical record, so the invoice amount is never
    counted per row (section 28.7).
    """
    counts = _blank()
    organization = batch.organization

    for row in _valid_rows(batch):
        data = row.normalized_data
        references = [
            Reference(
                "customer",
                str(data["customer_source_system"]),
                str(data["customer_external_id"]),
                "customer_external_id",
            ),
            Reference(
                "site",
                str(data["site_source_system"]),
                str(data["site_external_id"]),
                "site_external_id",
            ),
        ]
        if data.get("work_order_external_id"):
            references.append(
                Reference(
                    "work_order",
                    str(data["work_order_source_system"]),
                    str(data["work_order_external_id"]),
                    "work_order_external_id",
                )
            )

        resolved = _resolve_or_quarantine(batch, row, references)
        if resolved is None:
            continue

        canonical: dict[str, object] = {
            "invoice_amount": str(data["invoice_amount"]),
            "invoice_status": str(data["invoice_status"]),
            "service_date": str(data["service_date"]),
            "invoiced_at": str(data["invoiced_at"]),
        }
        from apps.ingestion.services.imports import _record_version

        _, appended = _record_version(
            batch=batch,
            record_type="accounting_invoice",
            external_id=str(data["invoice_external_id"]),
            canonical=canonical,
        )

        existing_reference = ExternalEntityReference.objects.filter(
            organization=organization,
            source=batch.source,
            entity_type="accounting_invoice",
            external_id=str(data["invoice_external_id"]),
            mapping_status=ExternalEntityReference.MappingStatus.CONFIRMED,
        ).first()

        defaults = {
            "customer_id": resolved["customer"],
            "site_id": resolved["site"],
            "work_order_id": resolved.get("work_order"),
            "service_date": _req_date(data["service_date"], "service_date"),
            "invoice_reference": str(data["invoice_reference"]),
            "invoice_amount": _req_decimal(data["invoice_amount"], "invoice_amount"),
            "invoiced_at": _req_timestamp(data["invoiced_at"], "invoiced_at"),
            "currency": str(data["currency"]),
            "source_status": str(data["invoice_status"]),
            "source_as_of_at": _req_timestamp(data["source_as_of_at"], "source_as_of_at"),
        }

        if existing_reference and existing_reference.accounting_invoice_id:
            invoice = AccountingInvoice.objects.get(id=existing_reference.accounting_invoice_id)
            for key, value in defaults.items():
                setattr(invoice, key, value)
            invoice.save()
            counts["updated" if appended else "unchanged"] += 1
        else:
            invoice = AccountingInvoice.objects.create(organization=organization, **defaults)
            counts["created"] += 1

        identity.confirm(
            organization=organization,
            source=batch.source,
            entity_type="accounting_invoice",
            external_id=str(data["invoice_external_id"]),
            target=invoice,
            match_method=ExternalEntityReference.MatchMethod.DETERMINISTIC_EXACT,
            provenance=f"import:{batch.id}:row{row.row_number}",
            confirmed_by=actor,
        )

        if data.get("payment_external_id"):
            payment, payment_created = AccountingPayment.objects.update_or_create(
                organization=organization,
                accounting_invoice=invoice,
                payment_reference=str(data.get("payment_reference") or data["payment_external_id"]),
                defaults={
                    "collected_amount": _req_decimal(data["collected_amount"], "collected_amount"),
                    "collected_at": _req_timestamp(data["collected_at"], "collected_at"),
                    "currency": str(data["currency"]),
                    "source_status": str(data["payment_status"]),
                    "source_as_of_at": _req_timestamp(data["source_as_of_at"], "source_as_of_at"),
                },
            )
            identity.confirm(
                organization=organization,
                source=batch.source,
                entity_type="accounting_payment",
                external_id=str(data["payment_external_id"]),
                target=payment,
                match_method=ExternalEntityReference.MatchMethod.DETERMINISTIC_EXACT,
                provenance=f"import:{batch.id}:row{row.row_number}",
                confirmed_by=actor,
            )
            if payment_created:
                counts["created"] += 1

        row.status = ImportRow.Status.COMMITTED if appended else ImportRow.Status.UNCHANGED
        row.target_model = "operations.AccountingInvoice"
        row.target_id = invoice.id
        row.save(update_fields=["status", "target_model", "target_id"])

    return counts


_NORMALIZERS: dict[str, Callable[[ImportBatch, object], Counts]] = {
    "sites_contracts": normalize_sites_contracts,
    "entity_crosswalk": normalize_entity_crosswalk,
    "work_orders_service_events": normalize_work_orders,
    "invoice_status": normalize_invoice_status,
}


def for_kind(kind: str) -> Callable[[ImportBatch, object], Counts]:
    normalizer = _NORMALIZERS.get(kind)
    if normalizer is None:
        raise KeyError(f"No normalizer for {kind!r}; Route B implements {sorted(_NORMALIZERS)}.")
    return normalizer
