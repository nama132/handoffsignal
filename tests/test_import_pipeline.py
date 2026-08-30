"""Upload, preview, commit, replay, quarantine, and reconciliation readiness.

These are the Phase 3 required tests (line 2513) that go beyond parsing: the ones that
prove the import boundary is safe rather than merely well-formed.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from django.conf import settings
from django.db import IntegrityError, transaction

from apps.ingestion.errors import ErrorCode
from apps.ingestion.models import (
    DataSource,
    ExternalEntityReference,
    IdentityResolutionIssue,
    ImportBatch,
    ImportCoverage,
    ImportRow,
    ReconciliationRun,
    SourceRecordVersion,
)
from apps.ingestion.services import coverage as coverage_service
from apps.ingestion.services import imports as import_service
from apps.ingestion.services import reconciliation as reconciliation_service
from apps.operations.models import (
    AccountingInvoice,
    AccountingPayment,
    CustomerAccount,
    ServiceObligation,
    Site,
    WorkOrder,
)
from apps.organizations.models import Organization, User

pytestmark = pytest.mark.django_db

FIXTURES = Path(settings.BASE_DIR) / "sample_data" / "atlas_facility_services"
AS_OF = dt.datetime(2026, 8, 20, 10, 0, tzinfo=dt.UTC)

PLAN = [
    ("sites_contracts.csv", "sites_contracts", "contract_register", "contract_scope", ""),
    ("entity_crosswalk.csv", "entity_crosswalk", "opsplatform_idmap", "entity_crosswalk", ""),
    (
        "work_orders_service_events.csv",
        "work_orders_service_events",
        "opsplatform_workorders",
        "work_order",
        "SERVICE_EVENT_CURRENT_STATE_V1",
    ),
    (
        "invoice_status.csv",
        "invoice_status",
        "ar_ledger",
        "accounting_invoice",
        "ACCOUNTING_SERVICE_DATE_LEDGER_V1",
    ),
]


def declaration(family: str, query_contract: str = "", completeness: str = "complete"):  # type: ignore[no-untyped-def]
    return coverage_service.CoverageDeclaration(
        record_family=family,
        scope_type="organization",
        coverage_start_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        coverage_end_at=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
        query_contract_code=query_contract,
        query_contract_version=1,
        completeness=completeness,
        declaration_basis="synthetic_fixture",
    )


@pytest.fixture
def atlas(django_user_model, settings):  # type: ignore[no-untyped-def]
    settings.APP_ENV = "local"
    from django.core.management import call_command

    call_command("seed_demo", verbosity=0)
    organization = Organization.objects.get(slug="atlas-facility-services")
    actor = User.objects.get(email="owner@atlas.example")
    return organization, actor


def load(organization, actor, entry, payload=None):  # type: ignore[no-untyped-def]
    filename, kind, source_key, family, query_contract = entry
    source = DataSource.objects.get(organization=organization, system_key=source_key)
    return import_service.upload(
        organization=organization,
        source=source,
        kind=kind,
        filename=filename,
        payload=payload if payload is not None else (FIXTURES / filename).read_bytes(),
        observation_mode="full_snapshot",
        source_as_of_at=AS_OF,
        declarations=[declaration(family, query_contract)],
        actor=actor,
    )


def load_all(organization, actor, upto=None):  # type: ignore[no-untyped-def]
    batches = []
    for entry in PLAN[: upto or len(PLAN)]:
        result = load(organization, actor, entry)
        batches.append(import_service.commit(result.batch, actor))
    return batches


class TestPreviewWritesNothing:
    def test_preview_creates_no_operational_records(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        result = load(organization, actor, PLAN[0])
        before = (
            CustomerAccount.objects.filter(organization=organization).count(),
            Site.objects.filter(organization=organization).count(),
            ServiceObligation.objects.filter(organization=organization).count(),
            ExternalEntityReference.objects.filter(organization=organization).count(),
            SourceRecordVersion.objects.filter(organization=organization).count(),
        )
        import_service.preview(result.batch)
        after = (
            CustomerAccount.objects.filter(organization=organization).count(),
            Site.objects.filter(organization=organization).count(),
            ServiceObligation.objects.filter(organization=organization).count(),
            ExternalEntityReference.objects.filter(organization=organization).count(),
            SourceRecordVersion.objects.filter(organization=organization).count(),
        )
        assert before == after

    def test_upload_alone_creates_no_operational_records(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        before = WorkOrder.objects.filter(organization=organization).count()
        load_all(organization, actor, upto=2)
        load(organization, actor, PLAN[2])  # uploaded, never committed
        assert WorkOrder.objects.filter(organization=organization).count() == before


class TestCommitCounts:
    def test_first_commit_reports_created(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        batch = load_all(organization, actor, upto=1)[0]
        assert batch.status == ImportBatch.Status.COMMITTED
        assert batch.created_count == 3
        assert batch.updated_count == 0

    def test_full_load_produces_the_expected_records(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor)
        assert WorkOrder.objects.filter(organization=organization).count() == 4
        # Three invoice rows, two canonical invoices: the repeated invoice is normalized
        # once and its two payments counted separately (section 28.7).
        assert AccountingInvoice.objects.filter(organization=organization).count() == 2
        assert AccountingPayment.objects.filter(organization=organization).count() == 2

    def test_invoice_amount_is_not_counted_once_per_payment_row(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor)
        invoice = AccountingInvoice.objects.get(organization=organization, invoice_reference="3310")
        # The invoice appears on two payment rows; its amount is stored once.
        assert str(invoice.invoice_amount) == "1200.0000"
        assert invoice.payments.count() == 2
        assert sum(p.collected_amount for p in invoice.payments.all()) == 1200


class TestReplayIdempotency:
    def test_exact_replay_reuses_the_same_batch(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        first = load_all(organization, actor, upto=1)[0]
        replay = load(organization, actor, PLAN[0])
        assert replay.duplicate_of is not None
        assert replay.batch.id == first.id
        assert ImportBatch.objects.filter(organization=organization).count() == 1

    def test_exact_replay_appends_no_source_version(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor, upto=1)
        before = SourceRecordVersion.objects.filter(organization=organization).count()
        load(organization, actor, PLAN[0])
        assert SourceRecordVersion.objects.filter(organization=organization).count() == before

    def test_replay_creates_no_duplicate_operational_records(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor)
        counts = (
            WorkOrder.objects.filter(organization=organization).count(),
            AccountingInvoice.objects.filter(organization=organization).count(),
            ServiceObligation.objects.filter(organization=organization).count(),
        )
        for entry in PLAN:
            load(organization, actor, entry)
        assert counts == (
            WorkOrder.objects.filter(organization=organization).count(),
            AccountingInvoice.objects.filter(organization=organization).count(),
            ServiceObligation.objects.filter(organization=organization).count(),
        )

    def test_committing_twice_is_a_no_op(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        batch = load_all(organization, actor, upto=1)[0]
        again = import_service.commit(batch, actor)
        assert again.status == ImportBatch.Status.COMMITTED
        assert again.created_count == batch.created_count

    def test_a_later_source_as_of_is_a_new_observation(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Section 22.3: the same bytes at a later legitimate as-of time is new."""
        organization, actor = atlas
        load_all(organization, actor, upto=1)
        source = DataSource.objects.get(organization=organization, system_key="contract_register")
        result = import_service.upload(
            organization=organization,
            source=source,
            kind="sites_contracts",
            filename="sites_contracts.csv",
            payload=(FIXTURES / "sites_contracts.csv").read_bytes(),
            observation_mode="full_snapshot",
            source_as_of_at=AS_OF + dt.timedelta(days=1),
            declarations=[declaration("contract_scope")],
            actor=actor,
        )
        assert result.duplicate_of is None
        assert ImportBatch.objects.filter(organization=organization).count() == 2


class TestChangedSourceHistory:
    def test_a_changed_row_appends_a_version_without_rewriting_history(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor)
        before = SourceRecordVersion.objects.filter(
            organization=organization, record_type="work_order"
        ).count()

        changed = (
            (FIXTURES / "work_orders_service_events.csv").read_text().replace("480.00", "525.00")
        )
        source = DataSource.objects.get(
            organization=organization, system_key="opsplatform_workorders"
        )
        result = import_service.upload(
            organization=organization,
            source=source,
            kind="work_orders_service_events",
            filename="work_orders_service_events.csv",
            payload=changed.encode(),
            observation_mode="full_snapshot",
            source_as_of_at=AS_OF + dt.timedelta(days=1),
            declarations=[declaration("work_order", "SERVICE_EVENT_CURRENT_STATE_V1")],
            actor=actor,
        )
        import_service.commit(result.batch, actor)

        after = SourceRecordVersion.objects.filter(
            organization=organization, record_type="work_order"
        ).count()
        assert after == before + 1, "a changed row must append exactly one version"

        latest = (
            SourceRecordVersion.objects.filter(
                organization=organization, record_type="work_order", external_id="00518774"
            )
            .order_by("-imported_at")
            .first()
        )
        assert latest.supersedes is not None, "history must chain, not be overwritten"
        # The normalized current view moved; the old version is still queryable.
        work_order = WorkOrder.objects.get(
            organization=organization, title__startswith="Post-construction"
        )
        assert str(work_order.approved_fixed_amount) == "525.0000"
        assert (
            SourceRecordVersion.objects.filter(
                organization=organization, external_id="00518774"
            ).count()
            == 2
        )

    def test_source_versions_are_append_only(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor, upto=1)
        version = SourceRecordVersion.objects.filter(organization=organization).first()
        with pytest.raises(IntegrityError), transaction.atomic():
            SourceRecordVersion.objects.create(
                organization=organization,
                source=version.source,
                record_type=version.record_type,
                external_id=version.external_id,
                version_hash=version.version_hash,
                canonical_data={},
                import_batch=version.import_batch,
            )


class TestQuarantine:
    def test_an_unresolved_reference_quarantines_the_row(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """The Potomac accounting site has no crosswalk row on purpose."""
        organization, actor = atlas
        load_all(organization, actor)
        batch = ImportBatch.objects.get(organization=organization, kind="invoice_status")
        quarantined = batch.rows.filter(status=ImportRow.Status.INVALID)
        assert quarantined.count() == 1
        codes = {e["code"] for row in quarantined for e in row.error_codes}
        assert ErrorCode.UNRESOLVED_IDENTITY in codes

    def test_the_quarantined_record_is_not_imported(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor)
        assert not AccountingInvoice.objects.filter(
            organization=organization, invoice_reference="3402"
        ).exists()

    def test_an_identity_issue_is_opened_for_a_human(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor)
        issues = IdentityResolutionIssue.objects.filter(
            organization=organization, status=IdentityResolutionIssue.Status.UNRESOLVED
        )
        assert issues.count() == 1
        assert issues.first().entity_type == "site"

    def test_facts_arriving_before_their_parent_are_quarantined_not_guessed(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Section 27: load order matters; an early fact waits rather than inventing a parent."""
        organization, actor = atlas
        load_all(organization, actor, upto=1)  # contracts only, no crosswalk yet
        result = load(organization, actor, PLAN[2])  # work orders reference ops ids
        import_service.commit(result.batch, actor)
        assert WorkOrder.objects.filter(organization=organization).count() == 0
        assert result.batch.rows.filter(status=ImportRow.Status.INVALID).count() == 4


class TestManualIdentityResolution:
    def test_owner_resolution_unblocks_the_reference(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor)
        issue = IdentityResolutionIssue.objects.get(
            organization=organization, status=IdentityResolutionIssue.Status.UNRESOLVED
        )
        site = Site.objects.get(organization=organization, name="Potomac Distribution Annex")

        from apps.ingestion.services import identity

        reference = identity.resolve_issue_manually(
            issue=issue, target=site, resolved_by=actor, note="Confirmed against register"
        )
        issue.refresh_from_db()
        assert issue.status == IdentityResolutionIssue.Status.RESOLVED
        assert issue.resolved_by == actor
        assert issue.resolved_at is not None
        assert reference.mapping_status == ExternalEntityReference.MappingStatus.CONFIRMED
        assert reference.match_method == ExternalEntityReference.MatchMethod.MANUAL
        assert not identity.has_blocking_issues(organization.id)

    def test_conflicting_crosswalk_is_refused_not_silently_remapped(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor, upto=2)
        from apps.ingestion.services import identity

        source = DataSource.objects.get(organization=organization, system_key="opsplatform_idmap")
        first = CustomerAccount.objects.filter(organization=organization).first()
        second = (
            CustomerAccount.objects.filter(organization=organization).exclude(id=first.id).first()
        )
        identity.confirm(
            organization=organization,
            source=source,
            entity_type="customer",
            external_id="ALIAS-1",
            target=first,
            match_method=ExternalEntityReference.MatchMethod.MANUAL,
            provenance="test",
            confirmed_by=actor,
        )
        with pytest.raises(identity.Unresolved) as exc:
            identity.confirm(
                organization=organization,
                source=source,
                entity_type="customer",
                external_id="ALIAS-1",
                target=second,
                match_method=ExternalEntityReference.MatchMethod.MANUAL,
                provenance="test",
                confirmed_by=actor,
            )
        assert exc.value.error.code == ErrorCode.CONFLICTING_CROSSWALK


class TestCoverageDeclarations:
    def test_missing_declaration_is_refused(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        source = DataSource.objects.get(organization=organization, system_key="ar_ledger")
        result = import_service.upload(
            organization=organization,
            source=source,
            kind="invoice_status",
            filename="x.csv",
            payload=b"",
            observation_mode="full_snapshot",
            source_as_of_at=AS_OF,
            declarations=[],
            actor=actor,
        )
        assert result.batch is None
        assert ErrorCode.COVERAGE_MANIFEST_MISSING in [e.code for e in result.file_errors]

    def test_wrong_query_contract_is_refused(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        source = DataSource.objects.get(organization=organization, system_key="ar_ledger")
        result = import_service.upload(
            organization=organization,
            source=source,
            kind="invoice_status",
            filename="x.csv",
            payload=b"",
            observation_mode="full_snapshot",
            source_as_of_at=AS_OF,
            declarations=[declaration("accounting_invoice", "SCHEDULE_OVERLAP_V1")],
            actor=actor,
        )
        assert ErrorCode.COVERAGE_QUERY_CONTRACT_INVALID in [e.code for e in result.file_errors]

    def test_inverted_interval_is_refused(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        source = DataSource.objects.get(organization=organization, system_key="ar_ledger")
        bad = coverage_service.CoverageDeclaration(
            record_family="accounting_invoice",
            scope_type="organization",
            coverage_start_at=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
            coverage_end_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            query_contract_code="ACCOUNTING_SERVICE_DATE_LEDGER_V1",
            query_contract_version=1,
            completeness="complete",
            declaration_basis="synthetic_fixture",
        )
        result = import_service.upload(
            organization=organization,
            source=source,
            kind="invoice_status",
            filename="x.csv",
            payload=b"",
            observation_mode="full_snapshot",
            source_as_of_at=AS_OF,
            declarations=[bad],
            actor=actor,
        )
        assert ErrorCode.COVERAGE_INTERVAL_INVALID in [e.code for e in result.file_errors]

    def test_non_authoritative_source_cannot_claim_completeness(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        source = DataSource.objects.get(organization=organization, system_key="ar_ledger")
        source.is_authoritative = False
        source.save()
        result = import_service.upload(
            organization=organization,
            source=source,
            kind="invoice_status",
            filename="x.csv",
            payload=b"",
            observation_mode="full_snapshot",
            source_as_of_at=AS_OF,
            declarations=[declaration("accounting_invoice", "ACCOUNTING_SERVICE_DATE_LEDGER_V1")],
            actor=actor,
        )
        assert ErrorCode.COVERAGE_NOT_AUTHORITATIVE in [e.code for e in result.file_errors]

    def test_only_a_complete_authoritative_snapshot_proves_absence(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor)
        batch = ImportBatch.objects.get(organization=organization, kind="invoice_status")
        row = batch.coverage_declarations.get()
        assert row.proves_absence is True

        row.completeness = ImportCoverage.Completeness.PARTIAL
        row.save()
        assert row.proves_absence is False

    def test_a_delta_observation_never_proves_absence(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor, upto=2)
        source = DataSource.objects.get(organization=organization, system_key="ar_ledger")
        result = import_service.upload(
            organization=organization,
            source=source,
            kind="invoice_status",
            filename="invoice_status.csv",
            payload=(FIXTURES / "invoice_status.csv").read_bytes(),
            observation_mode=ImportBatch.ObservationMode.DELTA,
            source_as_of_at=AS_OF,
            declarations=[declaration("accounting_invoice", "ACCOUNTING_SERVICE_DATE_LEDGER_V1")],
            actor=actor,
        )
        batch = import_service.commit(result.batch, actor)
        assert batch.coverage_declarations.get().proves_absence is False


class TestTransactionRollback:
    def test_a_failure_mid_commit_leaves_nothing_visible(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Section 27 step 7: a partially committed file must never become visible."""
        organization, actor = atlas
        load_all(organization, actor, upto=2)
        result = load(organization, actor, PLAN[2])

        before = WorkOrder.objects.filter(organization=organization).count()
        from unittest import mock

        with (
            mock.patch(
                "apps.ingestion.services.normalizers.identity.confirm",
                side_effect=RuntimeError("boom mid-commit"),
            ),
            pytest.raises(RuntimeError),
        ):
            import_service.commit(result.batch, actor)

        result.batch.refresh_from_db()
        assert WorkOrder.objects.filter(organization=organization).count() == before
        assert result.batch.status != ImportBatch.Status.COMMITTED

    def test_a_non_ready_batch_cannot_be_committed(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        source = DataSource.objects.get(organization=organization, system_key="ar_ledger")
        result = import_service.upload(
            organization=organization,
            source=source,
            kind="invoice_status",
            filename="bad.csv",
            payload=(FIXTURES / "invalid" / "invalid_blank_required.csv").read_bytes(),
            observation_mode="full_snapshot",
            source_as_of_at=AS_OF,
            declarations=[declaration("accounting_invoice", "ACCOUNTING_SERVICE_DATE_LEDGER_V1")],
            actor=actor,
        )
        if result.batch is not None:
            with pytest.raises(import_service.CommitRefused):
                import_service.commit(result.batch, actor)


class TestReconciliationReadiness:
    def test_run_waits_until_every_input_commits(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        run = reconciliation_service.open_run(organization=organization, run_key="r1", as_of=AS_OF)
        assert run.status == ReconciliationRun.Status.WAITING_INPUTS
        assert reconciliation_service.readiness_blockers(run)

        for batch in load_all(organization, actor):
            reconciliation_service.attach_batch(run, batch)

        run.refresh_from_db()
        assert "unresolved_identity" in reconciliation_service.readiness_blockers(run)

    def test_unresolved_identity_blocks_readiness(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        run = reconciliation_service.open_run(organization=organization, run_key="r2", as_of=AS_OF)
        for batch in load_all(organization, actor):
            reconciliation_service.attach_batch(run, batch)
        run = reconciliation_service.evaluate_readiness(run)
        assert run.status == ReconciliationRun.Status.WAITING_INPUTS

    def test_becomes_ready_exactly_once_after_resolution(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        run = reconciliation_service.open_run(organization=organization, run_key="r3", as_of=AS_OF)
        for batch in load_all(organization, actor):
            reconciliation_service.attach_batch(run, batch)

        from apps.ingestion.services import identity

        issue = IdentityResolutionIssue.objects.get(
            organization=organization, status=IdentityResolutionIssue.Status.UNRESOLVED
        )
        identity.resolve_issue_manually(
            issue=issue,
            target=Site.objects.get(organization=organization, name="Potomac Distribution Annex"),
            resolved_by=actor,
        )

        run = reconciliation_service.evaluate_readiness(run)
        assert run.status == ReconciliationRun.Status.READY
        first_ready_at = run.became_ready_at
        assert run.input_manifest_sha256

        # Re-evaluating must not move it again.
        run = reconciliation_service.evaluate_readiness(run)
        assert run.became_ready_at == first_ready_at

    def test_an_uncommitted_batch_cannot_satisfy_an_input(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        run = reconciliation_service.open_run(organization=organization, run_key="r4", as_of=AS_OF)
        result = load(organization, actor, PLAN[0])  # uploaded, not committed
        assert reconciliation_service.attach_batch(run, result.batch) is None

    def test_readiness_now_creates_the_dispatch_intent(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Phase 3 stopped at readiness; Phase 4 filled the seam (line 403).

        Exactly one durable intent per enabled detector is inserted in the readiness
        transaction. The reliability behaviour is covered in test_dispatch_reliability.
        """
        from apps.exceptions.models import DetectorDispatchIntent

        organization, actor = atlas
        run = reconciliation_service.open_run(organization=organization, run_key="r5", as_of=AS_OF)
        for batch in load_all(organization, actor):
            reconciliation_service.attach_batch(run, batch)
        assert DetectorDispatchIntent.objects.filter(reconciliation_run=run).count() == 0
        from apps.ingestion.services import identity

        issue = IdentityResolutionIssue.objects.get(
            organization=organization, status=IdentityResolutionIssue.Status.UNRESOLVED
        )
        identity.resolve_issue_manually(
            issue=issue,
            target=Site.objects.get(organization=organization, name="Potomac Distribution Annex"),
            resolved_by=actor,
        )
        run = reconciliation_service.evaluate_readiness(run)
        assert run.status == ReconciliationRun.Status.READY
        assert DetectorDispatchIntent.objects.filter(reconciliation_run=run).count() == 1

    def test_reopening_a_run_is_idempotent(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, _ = atlas
        first = reconciliation_service.open_run(
            organization=organization, run_key="same", as_of=AS_OF
        )
        second = reconciliation_service.open_run(
            organization=organization, run_key="same", as_of=AS_OF
        )
        assert first.id == second.id
        assert first.inputs.count() == 3


class TestCrossTenantRejection:
    def test_a_source_from_another_tenant_cannot_be_used(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        beacon = Organization.objects.get(slug="beacon-building-care")
        from tests.factories import DataSourceFactory

        foreign_source = DataSourceFactory(organization=beacon, system_key="foreign")
        batch = ImportBatch(
            organization=organization,
            source=foreign_source,
            kind="invoice_status",
            original_filename="x.csv",
            content_sha256="0" * 64,
            source_as_of_at=AS_OF,
            observation_mode="full_snapshot",
            coverage_manifest_sha256="0" * 64,
            uploaded_by=actor,
        )
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            batch.full_clean()

    def test_batches_are_organization_scoped(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor, upto=1)
        beacon = Organization.objects.get(slug="beacon-building-care")
        from apps.ingestion import selectors

        assert selectors.batches_for_organization(organization.id).count() == 1
        assert selectors.batches_for_organization(beacon.id).count() == 0


class TestSourceFreshness:
    def test_freshness_is_computed_from_the_source_as_of(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor, upto=1)
        from apps.ingestion import selectors

        rows = {
            r["source"].system_key: r
            for r in selectors.source_freshness(
                organization.id, now=AS_OF + dt.timedelta(minutes=30)
            )
        }
        assert rows["contract_register"]["status"] == "fresh"
        # A source that never imported is unknown, never assumed fresh.
        assert rows["ar_ledger"]["status"] == "unknown"

    def test_an_old_observation_is_stale(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization, actor = atlas
        load_all(organization, actor, upto=1)
        from apps.ingestion import selectors

        rows = {
            r["source"].system_key: r
            for r in selectors.source_freshness(organization.id, now=AS_OF + dt.timedelta(days=60))
        }
        assert rows["contract_register"]["status"] == "stale"
