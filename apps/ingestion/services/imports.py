"""Upload, preview, and commit.

The shape of the flow is fixed by section 16.1 and section 27:

    upload -> parse into immutable rows -> validate -> preview -> explicit human commit
    -> upsert by (organization, source, external_id) -> record source version

Three rules are load-bearing and are asserted by tests:

* **Preview writes nothing** to normalized operational records.
* **Commit is all-or-nothing.** Under the demo row limit the whole validated file
  promotes in one transaction; a partially committed file is never visible.
* **Exact replay does no semantic work.** The same bytes, mapping version, source-as-of
  and coverage manifest produce `unchanged` counts and no new source versions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from apps.ingestion.contracts.registry import get_contract
from apps.ingestion.errors import ErrorCode, RowError
from apps.ingestion.models import (
    DataSource,
    ImportBatch,
    ImportRow,
    SourceRecordVersion,
)
from apps.ingestion.parsing import content_hash, parse_csv, sanitize_filename
from apps.ingestion.services import coverage as coverage_service


class CommitRefused(Exception):
    """Raised when a batch is not in a state that may be committed."""


@dataclass
class UploadResult:
    batch: ImportBatch | None
    file_errors: list[RowError] = field(default_factory=list)
    duplicate_of: ImportBatch | None = None

    @property
    def accepted(self) -> bool:
        return self.batch is not None


def _version_hash(canonical: dict[str, object]) -> str:
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


#: For a contract where one identifier may legitimately span several rows, only these
#: columns are compared when deciding whether repeats agree. Section 28.7: an invoice
#: may appear once per payment, and only its invoice-scoped fields must match.
DUPLICATE_COMPARISON_COLUMNS: dict[str, tuple[str, ...]] = {
    "invoice_status": (
        "invoice_external_id",
        "customer_external_id",
        "site_external_id",
        "service_date",
        "invoice_reference",
        "invoice_amount",
        "invoiced_at",
        "invoice_status",
        "currency",
    ),
}


def _identity_columns(kind: str) -> str:
    """The column holding each row's own stable external identifier."""
    return {
        "sites_contracts": "service_obligation_external_id",
        "entity_crosswalk": "alias_external_id",
        "work_orders_service_events": "record_external_id",
        "invoice_status": "invoice_external_id",
    }[kind]


@transaction.atomic
def upload(
    *,
    organization,
    source: DataSource,
    kind: str,
    filename: str,
    payload: bytes,
    observation_mode: str,
    source_as_of_at,
    declarations: list[coverage_service.CoverageDeclaration],
    actor,
    mapping_version: int = 1,
) -> UploadResult:
    """Parse and validate a file into immutable rows. Writes no operational records."""
    contract = get_contract(kind)

    coverage_errors = coverage_service.validate_declarations(kind, source, declarations)
    if coverage_errors:
        return UploadResult(batch=None, file_errors=coverage_errors)

    manifest = coverage_service.manifest_hash(declarations)
    digest = content_hash(payload)

    existing = ImportBatch.objects.filter(
        organization=organization,
        source=source,
        kind=kind,
        content_sha256=digest,
        mapping_version=mapping_version,
        source_as_of_at=source_as_of_at,
        coverage_manifest_sha256=manifest,
    ).first()
    if existing is not None:
        # Exact replay of an identical observation. Section 27 step 10: this must not
        # create a duplicate batch, and the UI shows "unchanged/idempotent".
        return UploadResult(batch=existing, duplicate_of=existing)

    parsed = parse_csv(payload, expected_columns=contract.column_names)
    fatal = [e for e in parsed.file_errors if not e.is_warning]
    if fatal:
        return UploadResult(batch=None, file_errors=parsed.file_errors)

    batch = ImportBatch.objects.create(
        organization=organization,
        source=source,
        kind=kind,
        original_filename=sanitize_filename(filename),
        content_sha256=digest,
        mapping_version=mapping_version,
        source_as_of_at=source_as_of_at,
        observation_mode=observation_mode,
        coverage_manifest_sha256=manifest,
        uploaded_by=actor,
        status=ImportBatch.Status.VALIDATING,
    )
    coverage_service.persist_declarations(batch, declarations, actor)

    identity_column = _identity_columns(kind)
    seen: dict[str, str] = {}
    rows: list[ImportRow] = []
    valid_count = 0

    for parsed_row in parsed.rows:
        result = contract.validate_row(parsed_row.data, parsed_row.row_number)
        errors = [*parsed_row.errors, *result.errors]

        external_id = str(parsed_row.data.get(identity_column, ""))
        if external_id:
            comparison_columns = DUPLICATE_COMPARISON_COLUMNS.get(kind)
            comparable: dict[str, object] = (
                {c: parsed_row.data.get(c, "") for c in comparison_columns}
                if comparison_columns
                else dict(parsed_row.data)
            )
            fingerprint = _version_hash(comparable)
            if external_id in seen:
                # Repeated identifiers are allowed only when the rows agree exactly
                # (section 28.7 for invoices, 28.3 for repeated worker rows).
                if seen[external_id] != fingerprint:
                    # The repeats disagree on a field that must match exactly.
                    errors.append(
                        RowError(
                            ErrorCode.CONFLICTING_DUPLICATE,
                            column=identity_column,
                            row_number=parsed_row.row_number,
                        )
                    )
                elif comparison_columns is None:
                    # Identical repeats are only legitimate for contracts that expect
                    # one identifier across several rows.
                    errors.append(
                        RowError(
                            ErrorCode.DUPLICATE_EXTERNAL_ID_IN_FILE,
                            column=identity_column,
                            row_number=parsed_row.row_number,
                        )
                    )
            else:
                seen[external_id] = fingerprint

        blocking = [e for e in errors if not e.is_warning]
        status = ImportRow.Status.INVALID if blocking else ImportRow.Status.VALID
        if not blocking:
            valid_count += 1

        rows.append(
            ImportRow(
                organization=organization,
                import_batch=batch,
                row_number=parsed_row.row_number,
                raw_data=parsed_row.data,
                normalized_data=json.loads(json.dumps(result.values, default=str)),
                status=status,
                error_codes=[e.as_dict() for e in errors],
            )
        )

    ImportRow.objects.bulk_create(rows, batch_size=500)

    batch.total_row_count = len(rows)
    batch.valid_row_count = valid_count
    batch.invalid_row_count = len(rows) - valid_count
    batch.validated_at = timezone.now()
    batch.status = (
        ImportBatch.Status.READY if valid_count == len(rows) else ImportBatch.Status.INVALID
    )
    batch.save()
    return UploadResult(batch=batch, file_errors=parsed.file_errors)


def preview(batch: ImportBatch) -> dict[str, object]:
    """Read-only summary for the preview screen. Performs no writes at all."""
    rows = list(batch.rows.order_by("row_number")[:50])
    invalid = list(batch.rows.filter(status=ImportRow.Status.INVALID).order_by("row_number")[:100])
    error_totals: dict[str, int] = {}
    for row in batch.rows.filter(status=ImportRow.Status.INVALID):
        for error in row.error_codes:
            error_totals[error["code"]] = error_totals.get(error["code"], 0) + 1

    return {
        "batch": batch,
        "sample_rows": rows,
        "invalid_rows": invalid,
        "error_totals": sorted(error_totals.items(), key=lambda kv: (-kv[1], kv[0])),
        "coverage": list(batch.coverage_declarations.all()),
        "can_commit": batch.status == ImportBatch.Status.READY,
    }


def _record_version(
    *,
    batch: ImportBatch,
    record_type: str,
    external_id: str,
    canonical: dict[str, object],
) -> tuple[SourceRecordVersion, bool]:
    """Append a source version, or return the existing one unchanged.

    Append-only: an unchanged replay finds the same version hash and writes nothing.
    A changed row appends a new version pointing at its predecessor.
    """
    digest = _version_hash(canonical)
    existing = SourceRecordVersion.objects.filter(
        organization=batch.organization,
        source=batch.source,
        record_type=record_type,
        external_id=external_id,
        version_hash=digest,
    ).first()
    if existing is not None:
        return existing, False

    previous = (
        SourceRecordVersion.objects.filter(
            organization=batch.organization,
            source=batch.source,
            record_type=record_type,
            external_id=external_id,
        )
        .order_by("-imported_at")
        .first()
    )
    version = SourceRecordVersion.objects.create(
        organization=batch.organization,
        source=batch.source,
        record_type=record_type,
        external_id=external_id,
        version_hash=digest,
        canonical_data=json.loads(json.dumps(canonical, default=str)),
        import_batch=batch,
        supersedes=previous,
    )
    return version, True


@transaction.atomic
def commit(batch: ImportBatch, actor) -> ImportBatch:
    """Promote a fully validated file in one transaction.

    Refuses anything that is not `ready`. Section 27 step 7: "the whole validated file
    promotes in one database transaction... normalized records from a partially
    committed file must never become visible."
    """
    locked = ImportBatch.objects.select_for_update().get(pk=batch.pk)

    if locked.status == ImportBatch.Status.COMMITTED:
        return locked  # idempotent: committing twice is a no-op
    if locked.status != ImportBatch.Status.READY:
        raise CommitRefused(f"Batch status is {locked.status!r}; only 'ready' may be committed.")

    from apps.ingestion.services import normalizers

    normalizer = normalizers.for_kind(locked.kind)
    counts = normalizer(locked, actor)

    locked.created_count = counts["created"]
    locked.updated_count = counts["updated"]
    locked.unchanged_count = counts["unchanged"]
    locked.status = ImportBatch.Status.COMMITTED
    locked.committed_by = actor
    locked.committed_at = timezone.now()
    locked.save()

    locked.source.last_successful_import_at = locked.committed_at
    locked.source.last_source_as_of_at = locked.source_as_of_at
    locked.source.save(update_fields=["last_successful_import_at", "last_source_as_of_at"])

    if locked.source.domain == DataSource.Domain.INVOICE_STATUS:
        # New accounting facts are the only thing that can move an item from
        # "nobody has billed this" to invoiced or collected. Without this call the
        # ledger's confirmed columns would stay empty forever while the data to fill
        # them sat committed in the same database.
        from apps.recovery.services import accounting

        accounting.refresh_organization(locked.organization_id)

    return locked


@transaction.atomic
def reprocess_quarantined(batch: ImportBatch, actor) -> dict[str, int]:
    """Re-run normalization for rows quarantined on an identity error.

    Section 27: "If a fact arrives first, keep it quarantined and re-resolve after the
    relevant canonical entity/crosswalk commits; never guess." Until a batch's
    quarantined rows are promoted, its coverage declaration cannot prove absence.
    """
    identity_codes = {"unresolved_identity", "ambiguous_identity", "conflicting_crosswalk"}
    locked = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    if locked.status != ImportBatch.Status.COMMITTED:
        return {"reprocessed": 0}

    rows = list(locked.rows.filter(status=ImportRow.Status.INVALID))
    for row in rows:
        codes = {e["code"] for e in row.error_codes}
        if codes and codes <= identity_codes:
            row.status = ImportRow.Status.VALID
            row.error_codes = []
            row.save(update_fields=["status", "error_codes"])

    from apps.ingestion.services import normalizers

    counts = normalizers.for_kind(locked.kind)(locked, actor)
    locked.created_count += counts["created"]
    locked.updated_count += counts["updated"]
    locked.save(update_fields=["created_count", "updated_count", "updated_at"])
    return {"reprocessed": len(rows), **counts}


def quarantine_row(row: ImportRow, error: RowError) -> None:
    """Mark a row invalid at commit time because a reference did not resolve.

    Section 27 step 11: "Quarantine rows whose references are unresolved or ambiguous.
    Show them in an identity-resolution queue; do not let detectors consume them."
    """
    row.status = ImportRow.Status.INVALID
    row.error_codes = [*row.error_codes, error.as_dict()]
    row.save(update_fields=["status", "error_codes"])


__all__ = [
    "CommitRefused",
    "UploadResult",
    "commit",
    "preview",
    "quarantine_row",
    "upload",
]
