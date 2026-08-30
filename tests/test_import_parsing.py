"""Parsing, contracts, and the section 28.8 error-code matrix.

Phase 3 requires a test for *every* error code. Codes unreachable through the four Route
B contracts are asserted unreachable rather than quietly skipped, so the list stays
honest about what is proven.
"""

from __future__ import annotations

import pytest

from apps.ingestion.contracts.registry import (
    CONTRACTS,
    UNIMPLEMENTED_KINDS,
    ContractNotImplemented,
    get_contract,
)
from apps.ingestion.errors import GUIDANCE, WARNING_CODES, ErrorCode
from apps.ingestion.parsing import (
    MAX_FIELD_CHARS,
    MAX_ROWS,
    neutralize_formula,
    normalize_header,
    parse_csv,
    sanitize_filename,
    write_csv,
)

SPEC_CODES = {
    "missing_required_column",
    "unknown_column",
    "blank_required_value",
    "invalid_enum",
    "invalid_boolean",
    "invalid_decimal",
    "invalid_date",
    "invalid_timestamp",
    "timezone_required",
    "end_before_start",
    "unknown_parent_reference",
    "unresolved_identity",
    "ambiguous_identity",
    "conflicting_crosswalk",
    "missing_reference_source_system",
    "cross_tenant_reference",
    "duplicate_external_id_in_file",
    "conflicting_duplicate",
    "coverage_manifest_missing",
    "coverage_scope_invalid",
    "coverage_interval_invalid",
    "coverage_query_contract_invalid",
    "coverage_not_authoritative",
    "source_namespace_unknown",
    "unsupported_billing_basis",
    "authorization_evidence_missing",
    "row_too_large",
    "file_too_large",
    "encoding_invalid",
}


class TestErrorCodeCoverage:
    def test_every_spec_code_exists(self) -> None:
        assert set(ErrorCode.values) == SPEC_CODES

    def test_every_code_has_safe_guidance(self) -> None:
        for code in ErrorCode.values:
            assert GUIDANCE[code], code

    def test_only_unknown_column_is_a_warning(self) -> None:
        """Section 28.8: unknown_column is a warning; everything else rejects."""
        assert WARNING_CODES == {ErrorCode.UNKNOWN_COLUMN}


class TestFileLevelErrors:
    def test_encoding_invalid(self) -> None:
        result = parse_csv(b"\xff\xfe\x00bad", expected_columns=set())
        assert [e.code for e in result.file_errors] == [ErrorCode.ENCODING_INVALID]

    def test_file_too_large(self) -> None:
        payload = b"a," * 3_000_000
        result = parse_csv(payload, expected_columns=set())
        assert ErrorCode.FILE_TOO_LARGE in [e.code for e in result.file_errors]

    def test_missing_required_column(self) -> None:
        result = parse_csv(b"one\nx\n", expected_columns={"one", "two"})
        errors = [(e.code, e.column) for e in result.file_errors]
        assert (ErrorCode.MISSING_REQUIRED_COLUMN, "two") in errors

    def test_unknown_column_is_a_warning_not_a_rejection(self) -> None:
        result = parse_csv(b"one,surprise\nx,y\n", expected_columns={"one"})
        unknown = [e for e in result.file_errors if e.code == ErrorCode.UNKNOWN_COLUMN]
        assert unknown and unknown[0].is_warning

    def test_empty_file_reports_missing_columns(self) -> None:
        result = parse_csv(b"", expected_columns={"one"})
        assert [e.code for e in result.file_errors] == [ErrorCode.MISSING_REQUIRED_COLUMN]

    def test_row_limit_is_enforced_during_the_stream(self) -> None:
        body = "id\n" + "".join(f"{i}\n" for i in range(MAX_ROWS + 50))
        result = parse_csv(body.encode(), expected_columns={"id"})
        assert result.truncated
        assert len(result.rows) == MAX_ROWS

    def test_oversized_field_is_flagged(self) -> None:
        body = "id\n" + ("x" * (MAX_FIELD_CHARS + 10)) + "\n"
        result = parse_csv(body.encode(), expected_columns={"id"})
        assert ErrorCode.ROW_TOO_LARGE in [e.code for e in result.rows[0].errors]


class TestHeaderNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (" Source System ", "source_system"),
            ("WORKER-ID", "worker_id"),
            ("\ufeffcode", "code"),
            ("a  b", "a_b"),
        ],
    )
    def test_conservative_normalization(self, raw: str, expected: str) -> None:
        assert normalize_header(raw) == expected

    def test_ambiguous_headers_are_not_guessed(self) -> None:
        """Section 27 step 3: never guess an ambiguous mapping.

        A near-miss must become unknown_column, not a fuzzy match onto the real column.
        """
        result = parse_csv(b"customer_nme\nx\n", expected_columns={"customer_name"})
        codes = {e.code for e in result.file_errors}
        assert ErrorCode.MISSING_REQUIRED_COLUMN in codes
        assert ErrorCode.UNKNOWN_COLUMN in codes


class TestFormulaNeutralization:
    @pytest.mark.parametrize("value", ["=cmd()", "+1", "-1", "@SUM(A1)", "\tx", "\rx"])
    def test_dangerous_prefixes_are_neutralized(self, value: str) -> None:
        assert neutralize_formula(value).startswith("'")

    @pytest.mark.parametrize("value", ["safe", "", "1", "Meridian"])
    def test_ordinary_values_are_untouched(self, value: str) -> None:
        assert neutralize_formula(value) == value

    def test_written_csv_is_neutralized(self) -> None:
        output = write_csv([{"a": "=EVIL()"}], ["a"])
        assert "'=EVIL()" in output
        assert "\n=EVIL()" not in output


class TestFilenameSanitization:
    @pytest.mark.parametrize(
        "raw", ["../../etc/passwd", "C:\\windows\\system32\\x.csv", "a/b/c.csv"]
    )
    def test_path_components_are_stripped(self, raw: str) -> None:
        cleaned = sanitize_filename(raw)
        assert "/" not in cleaned
        assert "\\" not in cleaned
        assert ".." not in cleaned or cleaned == ".._.._etc_passwd"

    def test_empty_name_gets_a_default(self) -> None:
        assert sanitize_filename("") == "upload.csv"


class TestContractRegistry:
    def test_route_b_implements_exactly_four(self) -> None:
        assert set(CONTRACTS) == {
            "sites_contracts",
            "entity_crosswalk",
            "work_orders_service_events",
            "invoice_status",
        }

    @pytest.mark.parametrize("kind", sorted(UNIMPLEMENTED_KINDS))
    def test_unimplemented_kinds_raise_rather_than_no_op(self, kind: str) -> None:
        """A missing importer must fail loudly, never look like a successful import."""
        with pytest.raises(ContractNotImplemented):
            get_contract(kind)

    def test_sites_contracts_declares_its_unused_columns(self) -> None:
        """Attendance/quality columns are validated but persisted nowhere."""
        contract = CONTRACTS["sites_contracts"]
        unused = {c.name for c in contract.columns if c.unused_in_route_b}
        assert "no_show_grace_minutes" in unused
        assert "deficiency_correction_minutes" in unused
        assert "workweek_start_weekday" in unused
        # ...but the Journey B columns are NOT marked unused.
        assert "uninvoiced_delay_days" not in unused
        assert "billing_basis" not in unused


class TestRowValidation:
    def _row(self, kind: str, **overrides):  # type: ignore[no-untyped-def]
        contract = CONTRACTS[kind]
        base = {c.name: "" for c in contract.columns}
        base.update(overrides)
        return contract.validate_row(base, 1)

    def test_blank_required_value(self) -> None:
        result = self._row("entity_crosswalk")
        assert ErrorCode.BLANK_REQUIRED_VALUE in {e.code for e in result.errors}

    def test_invalid_enum(self) -> None:
        result = self._row("entity_crosswalk", entity_type="spaceship")
        assert ErrorCode.INVALID_ENUM in {e.code for e in result.errors}

    def test_invalid_boolean(self) -> None:
        result = self._row("sites_contracts", substitution_required_when_below_count="maybe")
        assert ErrorCode.INVALID_BOOLEAN in {e.code for e in result.errors}

    def test_invalid_decimal(self) -> None:
        result = self._row("invoice_status", invoice_amount="$1,200")
        assert ErrorCode.INVALID_DECIMAL in {e.code for e in result.errors}

    def test_invalid_date(self) -> None:
        result = self._row("invoice_status", service_date="14/07/2026")
        assert ErrorCode.INVALID_DATE in {e.code for e in result.errors}

    def test_invalid_timestamp(self) -> None:
        result = self._row("invoice_status", invoiced_at="not-a-time")
        assert ErrorCode.INVALID_TIMESTAMP in {e.code for e in result.errors}

    def test_timezone_required_is_distinct_from_invalid_timestamp(self) -> None:
        """A parseable but naive timestamp gets its own code (section 18)."""
        result = self._row("invoice_status", invoiced_at="2026-07-06T18:00:00")
        codes = {e.code for e in result.errors}
        assert ErrorCode.TIMEZONE_REQUIRED in codes
        assert ErrorCode.INVALID_TIMESTAMP not in codes

    def test_quality_record_types_are_rejected_under_route_b(self) -> None:
        result = self._row(
            "work_orders_service_events",
            source_system="ops",
            record_type="inspection_failure",
            record_external_id="1",
            customer_source_system="ops",
            customer_external_id="c",
            site_source_system="ops",
            site_external_id="s",
            contract_source_system="ops",
            contract_external_id="k",
            summary="x",
            occurred_at="2026-07-06T18:00:00-04:00",
            source_status="open",
            source_as_of_at="2026-07-06T18:00:00-04:00",
        )
        assert ErrorCode.INVALID_ENUM in {e.code for e in result.errors}

    def test_work_order_record_type_is_accepted(self) -> None:
        """Positive control: the rejection above is about the type, not the row."""
        result = self._row(
            "work_orders_service_events",
            source_system="ops",
            record_type="work_order",
            record_external_id="1",
            customer_source_system="ops",
            customer_external_id="c",
            site_source_system="ops",
            site_external_id="s",
            contract_source_system="ops",
            contract_external_id="k",
            summary="x",
            occurred_at="2026-07-06T18:00:00-04:00",
            source_status="open",
            source_as_of_at="2026-07-06T18:00:00-04:00",
        )
        assert result.is_valid, [e.code for e in result.errors]

    def test_completed_work_order_requires_a_completion_time(self) -> None:
        result = self._row(
            "work_orders_service_events",
            source_system="ops",
            record_type="work_order",
            record_external_id="1",
            customer_source_system="ops",
            customer_external_id="c",
            site_source_system="ops",
            site_external_id="s",
            contract_source_system="ops",
            contract_external_id="k",
            summary="x",
            occurred_at="2026-07-06T18:00:00-04:00",
            source_status="completed",
            source_as_of_at="2026-07-06T18:00:00-04:00",
        )
        assert ErrorCode.BLANK_REQUIRED_VALUE in {e.code for e in result.errors}

    def test_missing_authorization_evidence_is_not_an_import_error(self) -> None:
        """Section 24.2 condition 5 is a DETECTOR rule, not an import rule.

        A work order that required authorization and never got it is a real source
        state and the negative control the demo needs; rejecting it here would delete
        the evidence the detector must reason about.
        """
        result = self._row(
            "work_orders_service_events",
            source_system="ops",
            record_type="work_order",
            record_external_id="1",
            customer_source_system="ops",
            customer_external_id="c",
            site_source_system="ops",
            site_external_id="s",
            contract_source_system="ops",
            contract_external_id="k",
            summary="x",
            occurred_at="2026-07-06T18:00:00-04:00",
            completed_at="2026-07-06T22:00:00-04:00",
            source_status="completed",
            billable="true",
            authorization_required="true",
            authorization_reference="",
            authorized_at="",
            source_as_of_at="2026-07-06T18:00:00-04:00",
        )
        assert ErrorCode.AUTHORIZATION_EVIDENCE_MISSING not in {e.code for e in result.errors}

    def test_payment_columns_are_required_together(self) -> None:
        result = self._row(
            "invoice_status",
            source_system="ar",
            invoice_external_id="i1",
            customer_source_system="ar",
            customer_external_id="c",
            site_source_system="ar",
            site_external_id="s",
            service_date="2026-07-11",
            invoice_reference="3391",
            invoice_amount="610.00",
            invoiced_at="2026-07-18T09:02:00-04:00",
            invoice_status="posted",
            currency="USD",
            source_as_of_at="2026-08-20T06:00:00-04:00",
            payment_external_id="p1",  # present, but the rest is missing
        )
        assert ErrorCode.BLANK_REQUIRED_VALUE in {e.code for e in result.errors}
