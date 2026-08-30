"""REVENUE_COMPLETED_UNBILLED_V1 — the section 33.5 matrix.

Every negative test here is paired with the positive star case, so a detector that
matches nothing and a detector that matches everything both fail the suite.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.exceptions.detectors import revenue_unbilled as det
from apps.exceptions.detectors.base import SkipReason
from apps.ingestion.models import DataSource, ImportCoverage
from apps.operations.models import AccountingInvoice, ServiceObligation, WorkOrder
from tests.phase4_helpers import (
    AS_OF,
    invoice_csv_header_only,
    invoice_csv_with_star_invoice,
    load_atlas,
    seed_atlas,
    star_work_order,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def atlas(settings):  # type: ignore[no-untyped-def]
    settings.APP_ENV = "local"
    organization, actor = seed_atlas()
    return load_atlas(organization, actor)


def results_by_title(output, organization):  # type: ignore[no-untyped-def]
    out = {}
    for result in output.results:
        title = WorkOrder.objects.get(organization=organization, id=result.subject_id).title
        out[title.split(",")[0]] = result
    return out


class TestFixtureControls:
    """The four Atlas work orders, each with its expected verdict."""

    def test_exactly_one_match_and_three_reasoned_skips(self, atlas) -> None:  # type: ignore[no-untyped-def]
        output = det.evaluate(atlas.run, as_of=AS_OF)
        assert output.scanned == 4
        assert len(output.matches) == 1
        by = results_by_title(output, atlas.organization)
        assert by["Post-construction detail clean"].matched
        assert by["Quarterly floor burnish"].skip_reason == SkipReason.INVOICE_PRESENT
        assert by["Dock degrease requested on site"].skip_reason == SkipReason.AUTHORIZATION_MISSING
        assert by["Carpet extraction"].skip_reason == SkipReason.NOT_COMPLETED

    def test_the_star_case_carries_the_480_candidate(self, atlas) -> None:  # type: ignore[no-untyped-def]
        match = det.evaluate(atlas.run, as_of=AS_OF).matches[0]
        assert match.financial.basis == "fixed_work_order"
        assert match.financial.candidate_value == Decimal("480.0000")
        assert isinstance(match.financial.candidate_value, Decimal)

    def test_skip_reasons_are_counted(self, atlas) -> None:  # type: ignore[no-untyped-def]
        output = det.evaluate(atlas.run, as_of=AS_OF)
        assert output.skip_reasons == {
            SkipReason.INVOICE_PRESENT: 1,
            SkipReason.AUTHORIZATION_MISSING: 1,
            SkipReason.NOT_COMPLETED: 1,
        }


class TestUninvoicedDelayBoundary:
    """Section 33.5: threshold minus one second, exact, plus one second."""

    def _threshold(self, atlas) -> dt.datetime:  # type: ignore[no-untyped-def]
        work_order = star_work_order(atlas.organization)
        return work_order.completed_at + dt.timedelta(
            days=work_order.service_obligation.uninvoiced_delay_days
        )

    def test_one_second_before_threshold_does_not_match(self, atlas) -> None:  # type: ignore[no-untyped-def]
        moment = self._threshold(atlas) - dt.timedelta(seconds=1)
        by = results_by_title(det.evaluate(atlas.run, as_of=moment), atlas.organization)
        assert by["Post-construction detail clean"].skip_reason == SkipReason.DELAY_NOT_ELAPSED

    def test_exact_threshold_matches(self, atlas) -> None:  # type: ignore[no-untyped-def]
        by = results_by_title(
            det.evaluate(atlas.run, as_of=self._threshold(atlas)), atlas.organization
        )
        assert by["Post-construction detail clean"].matched

    def test_one_second_after_threshold_matches(self, atlas) -> None:  # type: ignore[no-untyped-def]
        moment = self._threshold(atlas) + dt.timedelta(seconds=1)
        by = results_by_title(det.evaluate(atlas.run, as_of=moment), atlas.organization)
        assert by["Post-construction detail clean"].matched


class TestNegativeEvidenceCoverage:
    """The heart of the claim: an EMPTY accounting file proves absence only when declared complete."""

    def test_empty_accounting_file_with_complete_coverage_proves_absence(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        organization, actor = seed_atlas()
        atlas = load_atlas(organization, actor, invoice_payload=invoice_csv_header_only())
        assert atlas.run.is_ready
        output = det.evaluate(atlas.run, as_of=AS_OF)
        by = results_by_title(output, organization)
        assert by["Post-construction detail clean"].matched
        # Without an invoice file the already-invoiced control ALSO becomes a match,
        # because the only thing that made it not-billable was the invoice.
        assert by["Quarterly floor burnish"].matched

    def test_empty_accounting_file_with_partial_coverage_cannot_prove_absence(
        self, settings
    ) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        organization, actor = seed_atlas()
        atlas = load_atlas(
            organization,
            actor,
            invoice_payload=invoice_csv_header_only(),
            invoice_completeness="partial",
        )
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), organization)
        assert by["Post-construction detail clean"].skip_reason == SkipReason.INSUFFICIENT_COVERAGE
        assert not det.evaluate(atlas.run, as_of=AS_OF).matches

    def test_unknown_coverage_cannot_prove_absence(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        organization, actor = seed_atlas()
        atlas = load_atlas(organization, actor, invoice_completeness="unknown")
        assert not det.evaluate(atlas.run, as_of=AS_OF).matches

    def test_delta_observation_cannot_prove_absence(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        organization, actor = seed_atlas()
        atlas = load_atlas(organization, actor, invoice_mode="delta")
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), organization)
        assert by["Post-construction detail clean"].skip_reason == SkipReason.INSUFFICIENT_COVERAGE

    def test_wrong_query_contract_cannot_prove_absence(self, atlas) -> None:  # type: ignore[no-untyped-def]
        cov = ImportCoverage.objects.get(
            organization=atlas.organization, record_family="accounting_invoice"
        )
        cov.query_contract_code = ImportCoverage.QueryContract.SCHEDULE_OVERLAP_V1
        cov.save()
        assert not det.evaluate(atlas.run, as_of=AS_OF).matches

    def test_coverage_interval_that_excludes_the_service_date_cannot_prove_absence(
        self, atlas
    ) -> None:  # type: ignore[no-untyped-def]
        cov = ImportCoverage.objects.get(
            organization=atlas.organization, record_family="accounting_invoice"
        )
        cov.coverage_start_at = dt.datetime(
            2026, 8, 1, tzinfo=dt.UTC
        )  # after the July 6 service date
        cov.save()
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)
        assert by["Post-construction detail clean"].skip_reason == SkipReason.INSUFFICIENT_COVERAGE

    def test_non_authoritative_source_cannot_prove_absence(self, atlas) -> None:  # type: ignore[no-untyped-def]
        source = DataSource.objects.get(organization=atlas.organization, system_key="ar_ledger")
        source.is_authoritative = False
        source.save()
        assert not det.evaluate(atlas.run, as_of=AS_OF).matches


class TestQuarantineAwareCoverage:
    def test_a_batch_with_quarantined_rows_cannot_prove_absence(self, settings) -> None:  # type: ignore[no-untyped-def]
        """The Potomac invoice row is quarantined until its identity resolves. While it
        sits unimported, the accounting batch is NOT a complete observation of its own
        file, so its coverage row must not prove absence for anyone."""
        settings.APP_ENV = "local"
        organization, actor = seed_atlas()
        atlas = load_atlas(organization, actor, resolve_identity=False)
        # Bypass the identity block to isolate the coverage rule itself.
        from django.utils import timezone

        from apps.ingestion.models import IdentityResolutionIssue

        IdentityResolutionIssue.objects.filter(organization=organization).update(
            status="rejected", resolved_by=actor, resolved_at=timezone.now()
        )
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), organization)
        assert by["Post-construction detail clean"].skip_reason == SkipReason.INSUFFICIENT_COVERAGE

    def test_resolving_the_identity_reprocesses_the_row_and_restores_coverage(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """After resolution the quarantined invoice is imported and coverage is whole again."""
        from apps.operations.models import AccountingInvoice

        assert AccountingInvoice.objects.filter(
            organization=atlas.organization, invoice_reference="3402"
        ).exists()
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)
        assert by["Post-construction detail clean"].matched


class TestAccountingInvoiceStates:
    def test_posted_invoice_for_the_star_case_suppresses_it(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        organization, actor = seed_atlas()
        atlas = load_atlas(
            organization, actor, invoice_payload=invoice_csv_with_star_invoice(status="posted")
        )
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), organization)
        assert by["Post-construction detail clean"].skip_reason == SkipReason.INVOICE_PRESENT

    def test_void_invoice_does_not_count_as_billing(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        organization, actor = seed_atlas()
        atlas = load_atlas(
            organization, actor, invoice_payload=invoice_csv_with_star_invoice(status="void")
        )
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), organization)
        assert by["Post-construction detail clean"].matched

    def test_invoice_matches_on_customer_site_and_service_date_without_a_work_order_id(
        self, atlas
    ) -> None:  # type: ignore[no-untyped-def]
        """The accounting fixtures carry no work-order id; the match runs on the crosswalk."""
        invoice = AccountingInvoice.objects.get(
            organization=atlas.organization, invoice_reference="3391"
        )
        assert invoice.work_order_id is None
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)
        assert by["Quarterly floor burnish"].skip_reason == SkipReason.INVOICE_PRESENT

    def test_stale_accounting_source_suppresses_every_claim(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Only the accounting BATCH on the manifest is aged, so the reason names accounting.

        Freshness is judged from the immutable batch the run selected, not from the
        mutable DataSource row - a later import must not change what this run saw.
        """
        batch = atlas.run.inputs.get(domain="invoice_status").import_batch
        batch.source_as_of_at = AS_OF - dt.timedelta(days=30)
        batch.save(update_fields=["source_as_of_at"])
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)
        assert by["Post-construction detail clean"].skip_reason == SkipReason.ACCOUNTING_STALE

    def test_stale_operations_source_suppresses_every_claim(self, atlas) -> None:  # type: ignore[no-untyped-def]
        batch = atlas.run.inputs.get(domain="service_events").import_batch
        batch.source_as_of_at = AS_OF - dt.timedelta(days=30)
        batch.save(update_fields=["source_as_of_at"])
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)
        assert by["Post-construction detail clean"].skip_reason == SkipReason.OPERATIONS_STALE

    def test_freshness_comes_from_the_manifest_not_the_mutable_source_row(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Ageing the DataSource row must NOT affect an already-selected manifest."""
        source = DataSource.objects.get(organization=atlas.organization, system_key="ar_ledger")
        source.last_source_as_of_at = AS_OF - dt.timedelta(days=365)
        source.save()
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)
        assert by["Post-construction detail clean"].matched


class TestEachConditionIndividually:
    def test_unbillable_work_is_skipped(self, atlas) -> None:  # type: ignore[no-untyped-def]
        wo = star_work_order(atlas.organization)
        wo.billable = False
        wo.save()
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)
        assert by["Post-construction detail clean"].skip_reason == SkipReason.NOT_BILLABLE

    def test_inactive_contract_is_skipped(self, atlas) -> None:  # type: ignore[no-untyped-def]
        wo = star_work_order(atlas.organization)
        wo.contract.status = "ended"
        wo.contract.save()
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)
        assert by["Post-construction detail clean"].skip_reason == SkipReason.CONTRACT_NOT_ACTIVE

    def test_included_billing_basis_owes_nothing(self, atlas) -> None:  # type: ignore[no-untyped-def]
        wo = star_work_order(atlas.organization)
        wo.billing_basis = ServiceObligation.BillingBasis.INCLUDED
        wo.save()
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)
        assert (
            by["Post-construction detail clean"].skip_reason == SkipReason.BILLING_BASIS_UNSUPPORTED
        )

    def test_missing_obligation_is_skipped(self, atlas) -> None:  # type: ignore[no-untyped-def]
        wo = star_work_order(atlas.organization)
        wo.service_obligation = None
        wo.save()
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)
        assert by["Post-construction detail clean"].skip_reason == SkipReason.NO_SERVICE_OBLIGATION

    def test_unresolved_identity_blocks_every_claim(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        organization, actor = seed_atlas()
        atlas = load_atlas(organization, actor, resolve_identity=False)
        output = det.evaluate(atlas.run, as_of=AS_OF)
        assert not output.matches
        assert output.skip_reasons == {SkipReason.BLOCKING_RECONCILIATION_ISSUE: 4}


class TestMoney:
    def test_missing_fixed_amount_yields_null_not_zero(self, atlas) -> None:  # type: ignore[no-untyped-def]
        wo = star_work_order(atlas.organization)
        wo.approved_fixed_amount = None
        wo.save()
        match = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)[
            "Post-construction detail clean"
        ]
        assert match.matched  # still flagged: the GAP is real even if the amount is unknown
        assert match.financial.candidate_value is None
        assert match.financial.basis == "manual_amount_required"

    def test_true_zero_is_distinguishable_from_unknown(self, atlas) -> None:  # type: ignore[no-untyped-def]
        wo = star_work_order(atlas.organization)
        wo.approved_fixed_amount = Decimal("0")
        wo.save()
        match = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)[
            "Post-construction detail clean"
        ]
        assert match.financial.candidate_value == Decimal("0")
        assert match.financial.candidate_value is not None

    def test_hourly_actual_multiplies_at_four_places(self, atlas) -> None:  # type: ignore[no-untyped-def]
        wo = star_work_order(atlas.organization)
        wo.billing_basis = ServiceObligation.BillingBasis.HOURLY_ACTUAL
        wo.approved_hours = Decimal("3.25")
        wo.bill_rate = Decimal("37.3333")
        wo.save()
        match = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)[
            "Post-construction detail clean"
        ]
        assert match.financial.basis == "hourly_actual"
        assert match.financial.candidate_value == Decimal("121.3332")
        assert match.financial.assumptions["approved_hours"] == "3.25"

    def test_hourly_without_a_rate_needs_a_human(self, atlas) -> None:  # type: ignore[no-untyped-def]
        wo = star_work_order(atlas.organization)
        wo.billing_basis = ServiceObligation.BillingBasis.HOURLY_ACTUAL
        wo.approved_hours = Decimal("3")
        wo.bill_rate = None
        wo.service_obligation.default_bill_rate = None
        wo.service_obligation.save()
        wo.save()
        match = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)[
            "Post-construction detail clean"
        ]
        assert match.financial.candidate_value is None
        assert match.financial.assumptions["missing"] == "bill_rate"

    def test_hourly_scheduled_always_needs_a_human_under_route_b(self, atlas) -> None:  # type: ignore[no-untyped-def]
        wo = star_work_order(atlas.organization)
        wo.billing_basis = ServiceObligation.BillingBasis.HOURLY_SCHEDULED
        wo.save()
        match = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)[
            "Post-construction detail clean"
        ]
        assert match.financial.candidate_value is None


class TestTimezone:
    """The service date comes from the SITE timezone, never UTC."""

    def test_evening_completion_stays_on_the_local_date(self, atlas) -> None:  # type: ignore[no-untyped-def]
        import zoneinfo

        ny = zoneinfo.ZoneInfo("America/New_York")
        wo = star_work_order(atlas.organization)
        # 23:30 New York on July 6 is 03:30 UTC on July 7. The occurrence must be July 6.
        wo.scheduled_at = dt.datetime(2026, 7, 6, 18, 0, tzinfo=ny)
        wo.completed_at = dt.datetime(2026, 7, 6, 23, 30, tzinfo=ny)
        wo.save()
        match = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)[
            "Post-construction detail clean"
        ]
        assert match.fingerprint_inputs["service_date"] == "2026-07-06"

    def test_overnight_completion_belongs_to_the_start_date(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Windows run 18:00-02:00. A job finishing at 01:30 on D+1 is a D occurrence.

        The accounting ledger dates it D. Searching only the completion date would miss
        that invoice and raise a false positive - the failure mode the reviewers flagged.
        """
        import zoneinfo

        ny = zoneinfo.ZoneInfo("America/New_York")
        wo = star_work_order(atlas.organization)
        wo.scheduled_at = dt.datetime(2026, 7, 6, 18, 0, tzinfo=ny)
        wo.completed_at = dt.datetime(2026, 7, 7, 1, 30, tzinfo=ny)
        wo.save()
        match = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)[
            "Post-construction detail clean"
        ]
        assert match.fingerprint_inputs["service_date"] == "2026-07-06"

    @pytest.mark.parametrize("invoice_date", ["2026-07-06", "2026-07-07"])
    def test_overnight_job_is_suppressed_by_an_invoice_on_either_date(
        self, settings, invoice_date
    ) -> None:  # type: ignore[no-untyped-def]
        """Either candidate date on the ledger counts as billed. Conservative by design."""
        import zoneinfo

        from tests.phase4_helpers import FIXTURES

        settings.APP_ENV = "local"
        organization, actor = seed_atlas()
        text = (FIXTURES / "invoice_status.csv").read_text().rstrip("\n")
        row = (
            "ar_ledger,80000998-1753900000,,,ar_ledger,80000042-1739216455,ar_ledger,80000107-1739216455,"
            f"{invoice_date},3451,480.00,2026-07-20T09:00:00-04:00,posted,,,,,,USD,,2026-08-20T06:00:00-04:00"
        )
        atlas = load_atlas(organization, actor, invoice_payload=(text + "\n" + row + "\n").encode())
        ny = zoneinfo.ZoneInfo("America/New_York")
        wo = star_work_order(organization)
        wo.scheduled_at = dt.datetime(2026, 7, 6, 18, 0, tzinfo=ny)
        wo.completed_at = dt.datetime(2026, 7, 7, 1, 30, tzinfo=ny)
        wo.save()
        by = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), organization)
        assert by["Post-construction detail clean"].skip_reason == SkipReason.INVOICE_PRESENT

    def test_dst_spring_forward_night(self, atlas) -> None:  # type: ignore[no-untyped-def]
        import zoneinfo

        ny = zoneinfo.ZoneInfo("America/New_York")
        wo = star_work_order(atlas.organization)
        wo.scheduled_at = dt.datetime(2026, 3, 8, 0, 30, tzinfo=ny)
        wo.completed_at = dt.datetime(2026, 3, 8, 1, 30, tzinfo=ny)  # 30 min before the 02:00 jump
        wo.save()
        match = results_by_title(det.evaluate(atlas.run, as_of=AS_OF), atlas.organization)[
            "Post-construction detail clean"
        ]
        assert match.fingerprint_inputs["service_date"] == "2026-03-08"

    def test_dst_fall_back_night(self, atlas) -> None:  # type: ignore[no-untyped-def]
        import zoneinfo

        ny = zoneinfo.ZoneInfo("America/New_York")
        wo = star_work_order(atlas.organization)
        wo.scheduled_at = dt.datetime(2026, 11, 1, 0, 30, tzinfo=ny)
        wo.completed_at = dt.datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=ny)  # the repeated hour
        wo.save()
        # Evaluate after the delay has elapsed, keeping every manifest batch fresh.
        later = dt.datetime(2026, 11, 20, 10, 0, tzinfo=dt.UTC)
        for run_input in atlas.run.inputs.all():
            if run_input.import_batch:
                run_input.import_batch.source_as_of_at = later
                run_input.import_batch.save(update_fields=["source_as_of_at"])
        match = results_by_title(det.evaluate(atlas.run, as_of=later), atlas.organization)[
            "Post-construction detail clean"
        ]
        assert match.fingerprint_inputs["service_date"] == "2026-11-01"


class TestFingerprint:
    def test_same_evaluation_twice_gives_the_same_fingerprint(self, atlas) -> None:  # type: ignore[no-untyped-def]
        first = det.evaluate(atlas.run, as_of=AS_OF).matches[0].fingerprint
        second = det.evaluate(atlas.run, as_of=AS_OF).matches[0].fingerprint
        assert first == second

    def test_a_new_service_date_is_a_new_occurrence(self, atlas) -> None:  # type: ignore[no-untyped-def]
        first = det.evaluate(atlas.run, as_of=AS_OF).matches[0].fingerprint
        wo = star_work_order(atlas.organization)
        wo.scheduled_at = wo.scheduled_at + dt.timedelta(days=7)
        wo.completed_at = wo.completed_at + dt.timedelta(days=7)
        wo.save()
        second = det.evaluate(atlas.run, as_of=AS_OF).matches[0].fingerprint
        assert first != second

    def test_a_rule_version_bump_is_a_new_fingerprint(self, atlas) -> None:  # type: ignore[no-untyped-def]
        match = det.evaluate(atlas.run, as_of=AS_OF).matches[0]
        original = match.fingerprint
        match.fingerprint_inputs["rule_version"] = "2"
        assert match.fingerprint != original


class TestDetectorPurity:
    def test_evaluate_writes_nothing(self, atlas) -> None:  # type: ignore[no-untyped-def]
        from apps.exceptions.models import ExceptionCase, FinancialImpactSnapshot

        det.evaluate(atlas.run, as_of=AS_OF)
        assert ExceptionCase.objects.count() == 0
        assert FinancialImpactSnapshot.objects.count() == 0

    def test_detector_module_makes_no_network_calls(self) -> None:
        import inspect

        source = inspect.getsource(det)
        for forbidden in ("requests.", "urllib", "socket.", "httpx", "smtplib", "boto3"):
            assert forbidden not in source
