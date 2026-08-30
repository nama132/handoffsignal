"""Import error codes (master prompt section 28.8).

Section 28.8 closes with the rule that governs presentation: "Do not expose stack
traces or raw rows to a normal user. Show row number, column, error code, and safe
corrective guidance."

Every code carries its guidance here so a view never has to invent wording, and so the
set stays auditable against the specification.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import models


class ErrorCode(models.TextChoices):
    MISSING_REQUIRED_COLUMN = "missing_required_column", "Missing required column"
    UNKNOWN_COLUMN = "unknown_column", "Unknown column"
    BLANK_REQUIRED_VALUE = "blank_required_value", "Blank required value"
    INVALID_ENUM = "invalid_enum", "Invalid value for a controlled list"
    INVALID_BOOLEAN = "invalid_boolean", "Invalid boolean"
    INVALID_DECIMAL = "invalid_decimal", "Invalid decimal"
    INVALID_DATE = "invalid_date", "Invalid date"
    INVALID_TIMESTAMP = "invalid_timestamp", "Invalid timestamp"
    TIMEZONE_REQUIRED = "timezone_required", "Timezone required"
    END_BEFORE_START = "end_before_start", "End is before start"
    UNKNOWN_PARENT_REFERENCE = "unknown_parent_reference", "Unknown parent reference"
    UNRESOLVED_IDENTITY = "unresolved_identity", "Unresolved identity"
    AMBIGUOUS_IDENTITY = "ambiguous_identity", "Ambiguous identity"
    CONFLICTING_CROSSWALK = "conflicting_crosswalk", "Conflicting crosswalk"
    MISSING_REFERENCE_SOURCE_SYSTEM = (
        "missing_reference_source_system",
        "Missing reference source system",
    )
    CROSS_TENANT_REFERENCE = "cross_tenant_reference", "Cross-tenant reference"
    DUPLICATE_EXTERNAL_ID_IN_FILE = "duplicate_external_id_in_file", "Duplicate external id in file"
    CONFLICTING_DUPLICATE = "conflicting_duplicate", "Conflicting duplicate rows"
    COVERAGE_MANIFEST_MISSING = "coverage_manifest_missing", "Coverage manifest missing"
    COVERAGE_SCOPE_INVALID = "coverage_scope_invalid", "Coverage scope invalid"
    COVERAGE_INTERVAL_INVALID = "coverage_interval_invalid", "Coverage interval invalid"
    COVERAGE_QUERY_CONTRACT_INVALID = (
        "coverage_query_contract_invalid",
        "Coverage query contract invalid",
    )
    COVERAGE_NOT_AUTHORITATIVE = "coverage_not_authoritative", "Coverage source not authoritative"
    SOURCE_NAMESPACE_UNKNOWN = "source_namespace_unknown", "Unknown source namespace"
    UNSUPPORTED_BILLING_BASIS = "unsupported_billing_basis", "Unsupported billing basis"
    AUTHORIZATION_EVIDENCE_MISSING = (
        "authorization_evidence_missing",
        "Authorization evidence missing",
    )
    ROW_TOO_LARGE = "row_too_large", "Row too large"
    FILE_TOO_LARGE = "file_too_large", "File too large"
    ENCODING_INVALID = "encoding_invalid", "Invalid encoding"


#: Safe, actionable guidance per code. Never contains the offending value.
GUIDANCE: dict[str, str] = {
    ErrorCode.MISSING_REQUIRED_COLUMN: "Add this column to the header row and re-export.",
    ErrorCode.UNKNOWN_COLUMN: "This column is not part of the contract and was ignored.",
    ErrorCode.BLANK_REQUIRED_VALUE: "Supply a value for this column in this row.",
    ErrorCode.INVALID_ENUM: "Use one of the values listed in the file-type documentation.",
    ErrorCode.INVALID_BOOLEAN: "Use true or false.",
    ErrorCode.INVALID_DECIMAL: "Use a plain decimal number without currency symbols or separators.",
    ErrorCode.INVALID_DATE: "Use the ISO format YYYY-MM-DD.",
    ErrorCode.INVALID_TIMESTAMP: "Use an ISO 8601 timestamp that includes a UTC offset.",
    ErrorCode.TIMEZONE_REQUIRED: "This timestamp needs an explicit UTC offset; the server timezone is never assumed.",
    ErrorCode.END_BEFORE_START: "The end value must be after the start value.",
    ErrorCode.UNKNOWN_PARENT_REFERENCE: "Import the parent record first, or correct the reference.",
    ErrorCode.UNRESOLVED_IDENTITY: "No confirmed crosswalk maps this identifier; resolve it in the identity queue.",
    ErrorCode.AMBIGUOUS_IDENTITY: "More than one canonical record matches; resolve it in the identity queue.",
    ErrorCode.CONFLICTING_CROSSWALK: "This mapping contradicts an existing confirmed mapping.",
    ErrorCode.MISSING_REFERENCE_SOURCE_SYSTEM: "Supply the source system for this reference; it is never guessed.",
    ErrorCode.CROSS_TENANT_REFERENCE: "This reference belongs to a different organization.",
    ErrorCode.DUPLICATE_EXTERNAL_ID_IN_FILE: "The same identifier appears more than once in this file.",
    ErrorCode.CONFLICTING_DUPLICATE: "Repeated rows for this identifier disagree; make them identical or remove one.",
    ErrorCode.COVERAGE_MANIFEST_MISSING: "Declare the observation mode and coverage scope on the import form.",
    ErrorCode.COVERAGE_SCOPE_INVALID: "The declared coverage scope does not name a valid target.",
    ErrorCode.COVERAGE_INTERVAL_INVALID: "The coverage interval must end after it starts.",
    ErrorCode.COVERAGE_QUERY_CONTRACT_INVALID: "The declared query contract is not on the allowlist for this record family.",
    ErrorCode.COVERAGE_NOT_AUTHORITATIVE: "Only an authoritative source may declare complete coverage.",
    ErrorCode.SOURCE_NAMESPACE_UNKNOWN: "Configure this source namespace before importing a file that references it.",
    ErrorCode.UNSUPPORTED_BILLING_BASIS: "Use a billing basis supported by the contract.",
    ErrorCode.AUTHORIZATION_EVIDENCE_MISSING: "Authorization is required for this record; supply the reference and date.",
    ErrorCode.ROW_TOO_LARGE: "This row exceeds the size limit; split or shorten the free-text fields.",
    ErrorCode.FILE_TOO_LARGE: "This file exceeds the demo size limit; export a narrower date range.",
    ErrorCode.ENCODING_INVALID: "Re-export the file as UTF-8.",
}

#: Codes that are warnings rather than rejections (section 28.8: "unknown_column as
#: warning unless unsafe").
WARNING_CODES: frozenset[str] = frozenset({ErrorCode.UNKNOWN_COLUMN})


@dataclass(frozen=True)
class RowError:
    """One safe, displayable problem with one row.

    Deliberately carries no value from the row: section 20 forbids raw source records
    reaching logs or error reporting.
    """

    code: str
    column: str = ""
    row_number: int | None = None

    @property
    def is_warning(self) -> bool:
        return self.code in WARNING_CODES

    @property
    def guidance(self) -> str:
        return GUIDANCE.get(self.code, "Correct this value and re-import.")

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "column": self.column,
            "row_number": self.row_number,
            "guidance": self.guidance,
            "is_warning": self.is_warning,
        }
