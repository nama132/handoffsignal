"""Local-only management commands.

Section 31: the seed command needs "a prominent guard that refuses outside local/demo
settings", must be idempotent, and must never be wired to a public route. The guard is
a security control, so it is tested as one.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.ingestion.models import DataSource
from apps.operations.models import Contract, ContractSite, CustomerAccount, ServiceObligation, Site
from apps.organizations.models import Membership, MembershipRoleGrant, Organization, User
from apps.organizations.roles import Role

pytestmark = pytest.mark.django_db


def run(command: str, *args: str) -> str:
    out = StringIO()
    call_command(command, *args, stdout=out, stderr=out)
    return out.getvalue()


class TestEnvironmentGuard:
    @pytest.mark.parametrize("command", ["seed_demo", "create_owner"])
    @pytest.mark.parametrize("app_env", ["pilot", "production", "staging"])
    def test_commands_refuse_outside_local_or_demo(self, settings, command, app_env) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = app_env
        with pytest.raises(CommandError) as exc:
            if command == "create_owner":
                call_command(command, "--email=x@example.test", "--organization=X")
            else:
                call_command(command)
        assert app_env in str(exc.value)

    @pytest.mark.parametrize("app_env", ["local", "test", "demo"])
    def test_seed_is_permitted_in_development_environments(self, settings, app_env) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = app_env
        run("seed_demo")
        assert Organization.objects.filter(slug="atlas-facility-services").exists()

    def test_no_public_route_exposes_seeding(self, client) -> None:  # type: ignore[no-untyped-def]
        for path in ("/seed/", "/app/seed/", "/seed_demo/", "/app/seed-demo/", "/reset/"):
            assert client.get(path).status_code == 404


class TestSeedDemo:
    def test_creates_the_atlas_organization_and_five_roles(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        run("seed_demo")
        atlas = Organization.objects.get(slug="atlas-facility-services")
        assert atlas.default_timezone == "America/New_York"
        assert atlas.demo_mode is True
        roles = set(
            MembershipRoleGrant.objects.filter(
                membership__organization=atlas, revoked_at=None
            ).values_list("role", flat=True)
        )
        assert roles == {
            Role.OWNER,
            Role.OPERATIONS_MANAGER,
            Role.SUPERVISOR,
            Role.FINANCE_REVIEWER,
            Role.AUDITOR,
        }

    def test_creates_three_customers_sites_contracts_and_obligations(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        run("seed_demo")
        atlas = Organization.objects.get(slug="atlas-facility-services")
        assert CustomerAccount.objects.filter(organization=atlas).count() == 3
        assert Site.objects.filter(organization=atlas).count() == 3
        assert Contract.objects.filter(organization=atlas).count() == 3
        assert ContractSite.objects.filter(organization=atlas).count() == 3
        assert ServiceObligation.objects.filter(organization=atlas).count() == 3

    def test_creates_four_distinct_data_sources(self, settings) -> None:  # type: ignore[no-untyped-def]
        """Route B ingests four contracts, so four sources exist — not seven."""
        settings.APP_ENV = "local"
        run("seed_demo")
        atlas = Organization.objects.get(slug="atlas-facility-services")
        keys = set(
            DataSource.objects.filter(organization=atlas).values_list("system_key", flat=True)
        )
        assert keys == {
            "contract_register",
            "opsplatform_workorders",
            "opsplatform_idmap",
            "ar_ledger",
        }

    def test_two_feeds_from_one_vendor_use_distinct_keys(self, settings) -> None:  # type: ignore[no-untyped-def]
        """Section 22.3 line 851 warns against sharing a system_key across feeds."""
        settings.APP_ENV = "local"
        run("seed_demo")
        atlas = Organization.objects.get(slug="atlas-facility-services")
        vendor_feeds = DataSource.objects.filter(
            organization=atlas, system_key__startswith="opsplatform"
        )
        assert vendor_feeds.count() == 2
        assert vendor_feeds.values("domain").distinct().count() == 2

    def test_creates_a_second_tenant_for_isolation_tests(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        run("seed_demo")
        beacon = Organization.objects.get(slug="beacon-building-care")
        assert Site.objects.filter(organization=beacon).count() == 1
        assert not Site.objects.filter(
            organization=beacon, name="Meridian Business Center"
        ).exists()

    def test_seeds_an_overnight_service_window(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        run("seed_demo")
        obligations = ServiceObligation.objects.filter(organization__slug="atlas-facility-services")
        assert all(o.crosses_midnight for o in obligations)

    def test_is_idempotent(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        run("seed_demo")
        counts = (
            Organization.objects.count(),
            Membership.objects.count(),
            Site.objects.count(),
            ServiceObligation.objects.count(),
            DataSource.objects.count(),
        )
        run("seed_demo")
        assert counts == (
            Organization.objects.count(),
            Membership.objects.count(),
            Site.objects.count(),
            ServiceObligation.objects.count(),
            DataSource.objects.count(),
        )

    def test_reset_clears_and_rebuilds(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        run("seed_demo")
        CustomerAccount.objects.create(
            organization=Organization.objects.get(slug="atlas-facility-services"),
            name="Stale Leftover Ltd",
        )
        output = run("seed_demo", "--reset")
        assert "removed" in output
        assert not CustomerAccount.objects.filter(name="Stale Leftover Ltd").exists()
        assert (
            CustomerAccount.objects.filter(organization__slug="atlas-facility-services").count()
            == 3
        )

    def test_seeds_no_journey_a_or_c_data(self, settings) -> None:  # type: ignore[no-untyped-def]
        """Route B: no workers, shifts, time entries, or quality events exist at all."""
        settings.APP_ENV = "local"
        output = run("seed_demo")
        assert "no workers, shifts, time entries, or quality events" in output
        from django.apps import apps

        model_names = {m.__name__ for m in apps.get_app_config("operations").get_models()}
        for absent in ("Worker", "Shift", "TimeEntry", "QualityEvent"):
            assert absent not in model_names


class TestCreateOwner:
    def test_creates_organization_user_and_owner_grant(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        run("create_owner", "--email=Boss@Example.TEST", "--organization=Northside Cleaning")
        user = User.objects.get(email="boss@example.test")
        organization = Organization.objects.get(slug="northside-cleaning")
        membership = Membership.objects.get(user=user, organization=organization)
        assert Role.OWNER in membership.active_roles

    def test_sets_no_password(self, settings) -> None:  # type: ignore[no-untyped-def]
        """A known default password must never exist."""
        settings.APP_ENV = "local"
        output = run("create_owner", "--email=nopw@example.test", "--organization=No Password Co")
        user = User.objects.get(email="nopw@example.test")
        assert not user.has_usable_password()
        assert "changepassword" in output

    def test_is_idempotent(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        args = ("--email=twice@example.test", "--organization=Twice Ltd")
        run("create_owner", *args)
        run("create_owner", *args)
        assert User.objects.filter(email="twice@example.test").count() == 1
        assert Organization.objects.filter(slug="twice-ltd").count() == 1
        assert (
            MembershipRoleGrant.objects.filter(
                membership__user__email="twice@example.test", revoked_at=None
            ).count()
            == 1
        )

    def test_new_owner_is_not_platform_staff(self, settings) -> None:  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        run("create_owner", "--email=tenant@example.test", "--organization=Tenant Only")
        assert User.objects.get(email="tenant@example.test").is_staff is False

    def test_rejects_an_invalid_timezone(self, settings) -> None:  # type: ignore[no-untyped-def]
        from django.core.exceptions import ValidationError

        settings.APP_ENV = "local"
        with pytest.raises(ValidationError):
            call_command(
                "create_owner",
                "--email=tz@example.test",
                "--organization=Bad TZ Co",
                "--timezone=Mars/Olympus",
            )
