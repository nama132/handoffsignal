"""Route contract and role enforcement for the import screens (section 29, 9.3)."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.urls import reverse

from apps.ingestion.models import DataSource, ImportBatch
from apps.organizations.models import Membership, MembershipRoleGrant, Organization, User
from apps.organizations.roles import Role

pytestmark = pytest.mark.django_db

FIXTURES = Path(settings.BASE_DIR) / "sample_data" / "atlas_facility_services"


@pytest.fixture
def atlas(settings):  # type: ignore[no-untyped-def]
    settings.APP_ENV = "local"
    call_command("seed_demo", verbosity=0)
    return Organization.objects.get(slug="atlas-facility-services")


def user_with(atlas, role):  # type: ignore[no-untyped-def]
    email = {
        Role.OWNER: "owner@atlas.example",
        Role.OPERATIONS_MANAGER: "ops@atlas.example",
        Role.SUPERVISOR: "supervisor@atlas.example",
        Role.FINANCE_REVIEWER: "finance@atlas.example",
        Role.AUDITOR: "auditor@atlas.example",
    }[role]
    return User.objects.get(email=email)


class TestRoutesExist:
    @pytest.mark.parametrize(
        "name", ["import-list", "import-new", "identity-queue", "reconciliation-queue"]
    )
    def test_named_routes_resolve(self, name: str) -> None:
        assert reverse(f"ingestion:{name}")

    @pytest.mark.parametrize("name", ["import-preview", "import-commit", "import-results"])
    def test_batch_routes_resolve(self, name: str) -> None:
        assert reverse(f"ingestion:{name}", kwargs={"batch_id": uuid.uuid4()})

    def test_all_routes_require_authentication(self, client) -> None:  # type: ignore[no-untyped-def]
        response = client.get(reverse("ingestion:import-list"))
        assert response.status_code == 302
        assert reverse("login") in response.url


class TestUploadPermissions:
    """Section 9.3 row 2: owner and operations manager may upload/preview."""

    @pytest.mark.parametrize("role", [Role.OWNER, Role.OPERATIONS_MANAGER])
    def test_permitted_roles_reach_the_upload_form(self, client, atlas, role) -> None:  # type: ignore[no-untyped-def]
        client.force_login(user_with(atlas, role))
        assert client.get(reverse("ingestion:import-new")).status_code == 200

    @pytest.mark.parametrize("role", [Role.SUPERVISOR, Role.AUDITOR])
    def test_denied_roles_are_refused(self, client, atlas, role) -> None:  # type: ignore[no-untyped-def]
        client.force_login(user_with(atlas, role))
        assert client.get(reverse("ingestion:import-new")).status_code == 403

    def test_everyone_may_view_the_import_history(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        client.force_login(user_with(atlas, Role.AUDITOR))
        assert client.get(reverse("ingestion:import-list")).status_code == 200


class TestCommitPermissions:
    """Rows 3-5: the commit permission depends on the FILE TYPE, not on visibility."""

    def _batch(self, atlas, kind, source_key, actor):  # type: ignore[no-untyped-def]
        from apps.ingestion.services import coverage as coverage_service
        from apps.ingestion.services import imports as import_service

        source = DataSource.objects.get(organization=atlas, system_key=source_key)
        family = {
            "sites_contracts": "contract_scope",
            "entity_crosswalk": "entity_crosswalk",
            "invoice_status": "accounting_invoice",
            "work_orders_service_events": "work_order",
        }[kind]
        qc = {
            "invoice_status": "ACCOUNTING_SERVICE_DATE_LEDGER_V1",
            "work_orders_service_events": "SERVICE_EVENT_CURRENT_STATE_V1",
        }.get(kind, "")
        result = import_service.upload(
            organization=atlas,
            source=source,
            kind=kind,
            filename=f"{kind}.csv",
            payload=(FIXTURES / f"{kind}.csv").read_bytes(),
            observation_mode="full_snapshot",
            source_as_of_at=dt.datetime(2026, 8, 20, tzinfo=dt.UTC),
            declarations=[
                coverage_service.CoverageDeclaration(
                    record_family=family,
                    scope_type="organization",
                    coverage_start_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                    coverage_end_at=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
                    query_contract_code=qc,
                    query_contract_version=1,
                    completeness="complete",
                    declaration_basis="synthetic_fixture",
                )
            ],
            actor=actor,
        )
        return result.batch

    def test_operations_manager_cannot_commit_a_financial_import(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        owner = user_with(atlas, Role.OWNER)
        batch = self._batch(atlas, "invoice_status", "ar_ledger", owner)
        client.force_login(user_with(atlas, Role.OPERATIONS_MANAGER))
        response = client.post(reverse("ingestion:import-commit", kwargs={"batch_id": batch.id}))
        assert response.status_code == 403
        batch.refresh_from_db()
        assert batch.status != ImportBatch.Status.COMMITTED

    def test_finance_reviewer_cannot_commit_an_operational_import(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        owner = user_with(atlas, Role.OWNER)
        batch = self._batch(atlas, "work_orders_service_events", "opsplatform_workorders", owner)
        client.force_login(user_with(atlas, Role.FINANCE_REVIEWER))
        response = client.post(reverse("ingestion:import-commit", kwargs={"batch_id": batch.id}))
        assert response.status_code == 403

    @pytest.mark.parametrize(
        "role", [Role.OPERATIONS_MANAGER, Role.FINANCE_REVIEWER, Role.SUPERVISOR, Role.AUDITOR]
    )
    def test_only_the_owner_may_commit_the_crosswalk(self, client, atlas, role) -> None:  # type: ignore[no-untyped-def]
        """Line 372: the identity boundary is owner-only."""
        owner = user_with(atlas, Role.OWNER)
        batch = self._batch(atlas, "entity_crosswalk", "opsplatform_idmap", owner)
        client.force_login(user_with(atlas, role))
        response = client.post(reverse("ingestion:import-commit", kwargs={"batch_id": batch.id}))
        assert response.status_code == 403

    def test_owner_may_commit_the_crosswalk(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        """Positive control for the denials above."""
        owner = user_with(atlas, Role.OWNER)
        self._batch(atlas, "sites_contracts", "contract_register", owner)
        from apps.ingestion.services import imports as import_service

        import_service.commit(
            ImportBatch.objects.get(organization=atlas, kind="sites_contracts"), owner
        )
        batch = self._batch(atlas, "entity_crosswalk", "opsplatform_idmap", owner)
        client.force_login(owner)
        response = client.post(reverse("ingestion:import-commit", kwargs={"batch_id": batch.id}))
        assert response.status_code == 302
        batch.refresh_from_db()
        assert batch.status == ImportBatch.Status.COMMITTED

    def test_commit_requires_post(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        owner = user_with(atlas, Role.OWNER)
        batch = self._batch(atlas, "sites_contracts", "contract_register", owner)
        client.force_login(owner)
        assert (
            client.get(
                reverse("ingestion:import-commit", kwargs={"batch_id": batch.id})
            ).status_code
            == 405
        )


class TestIdentityResolutionPermissions:
    @pytest.mark.parametrize(
        "role", [Role.OPERATIONS_MANAGER, Role.FINANCE_REVIEWER, Role.SUPERVISOR, Role.AUDITOR]
    )
    def test_only_the_owner_may_confirm_an_identity(self, client, atlas, role) -> None:  # type: ignore[no-untyped-def]
        client.force_login(user_with(atlas, role))
        response = client.post(
            reverse("ingestion:identity-resolve", kwargs={"issue_id": uuid.uuid4()})
        )
        assert response.status_code == 403

    def test_everyone_may_review_the_queue(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        client.force_login(user_with(atlas, Role.AUDITOR))
        response = client.get(reverse("ingestion:identity-queue"))
        assert response.status_code == 200
        # The sentence wraps in the template, so assert on a fragment within one line.
        assert b"organization owner may do it" in response.content


class TestCrossTenantAccess:
    def test_a_batch_from_another_tenant_returns_404(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        beacon = Organization.objects.get(slug="beacon-building-care")
        beacon_user = User.objects.get(email="owner@beacon.example")
        owner = user_with(atlas, Role.OWNER)

        from apps.ingestion.services import coverage as coverage_service
        from apps.ingestion.services import imports as import_service

        source = DataSource.objects.get(organization=atlas, system_key="contract_register")
        batch = import_service.upload(
            organization=atlas,
            source=source,
            kind="sites_contracts",
            filename="sites_contracts.csv",
            payload=(FIXTURES / "sites_contracts.csv").read_bytes(),
            observation_mode="full_snapshot",
            source_as_of_at=dt.datetime(2026, 8, 20, tzinfo=dt.UTC),
            declarations=[
                coverage_service.CoverageDeclaration(
                    record_family="contract_scope",
                    scope_type="organization",
                    coverage_start_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                    coverage_end_at=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
                    query_contract_code="",
                    query_contract_version=1,
                    completeness="complete",
                    declaration_basis="synthetic_fixture",
                )
            ],
            actor=owner,
        ).batch

        # Give the Beacon owner a role so the denial is about tenancy, not permissions.
        membership = Membership.objects.get(organization=beacon, user=beacon_user)
        MembershipRoleGrant.objects.get_or_create(
            membership=membership, role=Role.OWNER, revoked_at=None
        )
        client.force_login(beacon_user)
        for name in ("import-preview", "import-results"):
            response = client.get(reverse(f"ingestion:{name}", kwargs={"batch_id": batch.id}))
            assert response.status_code == 404, name
        assert (
            client.post(
                reverse("ingestion:import-commit", kwargs={"batch_id": batch.id})
            ).status_code
            == 404
        )


class TestPreviewScreen:
    def test_preview_states_that_nothing_is_imported_yet(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        owner = user_with(atlas, Role.OWNER)
        from apps.ingestion.services import coverage as coverage_service
        from apps.ingestion.services import imports as import_service

        source = DataSource.objects.get(organization=atlas, system_key="contract_register")
        batch = import_service.upload(
            organization=atlas,
            source=source,
            kind="sites_contracts",
            filename="sites_contracts.csv",
            payload=(FIXTURES / "sites_contracts.csv").read_bytes(),
            observation_mode="full_snapshot",
            source_as_of_at=dt.datetime(2026, 8, 20, tzinfo=dt.UTC),
            declarations=[
                coverage_service.CoverageDeclaration(
                    record_family="contract_scope",
                    scope_type="organization",
                    coverage_start_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                    coverage_end_at=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
                    query_contract_code="",
                    query_contract_version=1,
                    completeness="complete",
                    declaration_basis="synthetic_fixture",
                )
            ],
            actor=owner,
        ).batch
        client.force_login(owner)
        response = client.get(reverse("ingestion:import-preview", kwargs={"batch_id": batch.id}))
        assert response.status_code == 200
        assert b"Nothing has been imported yet" in response.content
        assert b"Commit import" in response.content
