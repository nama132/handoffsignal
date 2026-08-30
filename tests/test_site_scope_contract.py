"""A structural guard on the site-scope contract, so this defect class cannot recur.

Three separate reviews have now closed the same bug in three different places: the Phase 2
dashboard, the Phase 6 recovery ledger, and the Phase 2-of-this-plan cockpit. Each time it
was fixed on the one surface that was reported. This module tests the *class* instead.

Two rules, both deny-by-default:

1. Every public selector either accepts `limit_to_site_ids`, or is named here with a
   written justification for why its rows are not site-addressable. A new selector fails
   this test until somebody makes that decision deliberately.
2. Every selector that does accept it must return **nothing** for the empty set. That is
   the whole three-valued contract: `None` is tenant-wide, a set is those sites, and the
   empty set is no sites. Collapsing the empty set into "no filter" is the bug.
"""

from __future__ import annotations

import importlib
import inspect

import pytest

from tests.phase6_helpers import loaded_atlas

pytestmark = pytest.mark.django_db

SELECTOR_MODULES = [
    "apps.exceptions.selectors",
    "apps.ingestion.selectors",
    "apps.operations.selectors",
    "apps.organizations.selectors",
    "apps.recovery.selectors",
]

#: Selectors that legitimately have no site-scope parameter, each with the reason.
#: Adding a name here is a deliberate product decision, not a way to silence the test.
TENANT_HEALTH_SELECTORS: dict[str, str] = {
    # --- the tenant's data pipeline, not any site's business data -------------------
    "apps.exceptions.selectors.recent_runs": "DetectorRun describes the tenant's detector pipeline. It carries no site FK.",
    "apps.exceptions.selectors.failed_runs": "DetectorRun, as above. A failed run is a tenant-health fact.",
    "apps.ingestion.selectors.batches_for_organization": "ImportBatch is a file-level import record with no site FK.",
    "apps.ingestion.selectors.get_batch_or_none": "Fetches one ImportBatch by id within an organization. ImportBatch has no site foreign key, and every route reaching it is gated on an import action held only by tenant-wide roles.",
    "apps.ingestion.selectors.sources_for_organization": "DataSource is a configured source system, tenant-level by definition.",
    "apps.ingestion.selectors.source_freshness": "Freshness is a property of a DataSource, not of a site.",
    "apps.ingestion.selectors.open_identity_issues": "An IdentityResolutionIssue is by definition a reference that has NOT resolved to a "
    "canonical entity, so it has no site to be scoped to. This is the line that "
    "separates it from open_reconciliation_issues below -- do not 'fix' this one.",
    # --- people, not site data --------------------------------------------------------
    "apps.organizations.selectors.active_memberships_for": "Returns the requesting user's own memberships.",
    "apps.organizations.selectors.membership_for": "Resolves the requesting user's own membership in one organization. It returns tenant identity, not site business data, and it is what establishes the caller's scope -- scoping it by site would be circular.",
    # --- known gaps, recorded rather than hidden ---------------------------------------
    "apps.ingestion.selectors.open_reconciliation_issues_for": "Derives its scope FROM the membership rather than accepting one. That is the point: it is the single door every reconciliation surface uses, so the badge count and the queue list cannot drift apart. Accepting a site-scope argument would let a caller widen it, which is exactly what this function exists to prevent. The underlying open_reconciliation_issues does take limit_to_site_ids and is checked by the empty-set rule below.",
    "apps.recovery.selectors.exports_for_organization": "Finance exports are organization-level artifacts, and every surface that renders "
    "them is gated on EXPORT_FINANCE_CSV (owner/finance), both of which are tenant-wide "
    "roles. Unreachable by a site-scoped reader.",
}


def public_selectors():  # type: ignore[no-untyped-def]
    for module_path in SELECTOR_MODULES:
        module = importlib.import_module(module_path)
        for name, fn in sorted(vars(module).items()):
            if name.startswith("_") or not inspect.isfunction(fn):
                continue
            if fn.__module__ != module.__name__:
                continue
            yield f"{module_path}.{name}", fn


class TestEverySelectorIsClassified:
    def test_the_guard_can_see_the_selectors_at_all(self) -> None:
        """Non-vacuity: if discovery breaks, every other test here passes for free."""
        found = dict(public_selectors())
        assert len(found) >= 20, f"selector discovery found only {len(found)}"
        assert "apps.recovery.selectors.stage_totals" in found

    def test_each_selector_is_scoped_or_deliberately_exempt(self) -> None:
        unclassified = [
            name
            for name, fn in public_selectors()
            if "limit_to_site_ids" not in inspect.signature(fn).parameters
            and name not in TENANT_HEALTH_SELECTORS
        ]
        assert not unclassified, (
            "These selectors accept no site scope and are not on the tenant-health "
            "allowlist. Either add `limit_to_site_ids`, or add the name to "
            "TENANT_HEALTH_SELECTORS with a written reason:\n  " + "\n  ".join(unclassified)
        )

    def test_the_allowlist_has_no_stale_entries(self) -> None:
        """An exemption that no longer names a real selector is a lie in the record."""
        live = {name for name, _ in public_selectors()}
        stale = sorted(set(TENANT_HEALTH_SELECTORS) - live)
        assert not stale, f"allowlist names selectors that no longer exist: {stale}"

    def test_every_exemption_carries_a_real_justification(self) -> None:
        thin = [n for n, why in TENANT_HEALTH_SELECTORS.items() if len(why.strip()) < 40]
        assert not thin, f"exemptions without a real reason: {thin}"


class TestEmptyScopeReturnsNothing:
    """Rule 2, applied to every scoped selector at once against real data."""

    @pytest.fixture
    def atlas(self, settings):  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        return loaded_atlas()

    def _call(self, fn, organization_id, scope):  # type: ignore[no-untyped-def]
        params = inspect.signature(fn).parameters
        kwargs = {"limit_to_site_ids": scope}
        if "case_id" in params or "site_id" in params:
            return None  # single-object getters are covered by the view-level tests
        return fn(organization_id, **kwargs)

    @staticmethod
    def _emptiness(result) -> bool:  # type: ignore[no-untyped-def]
        if result is None:
            return True
        if isinstance(result, dict):
            values = [v for v in result.values() if isinstance(v, int | float)]
            return all(v == 0 for v in values) and not any(
                getattr(v, "is_finite", None) and v for v in result.values()
            )
        return len(list(result)) == 0

    def test_the_fixture_actually_contains_something(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Non-vacuity: an empty database would make every assertion below trivially true."""
        from apps.recovery import selectors as recovery_selectors

        assert recovery_selectors.stage_totals(atlas.organization.id)["candidate"] is not None
        assert len(list(recovery_selectors.ledger_items(atlas.organization.id))) >= 1

    def test_every_scoped_selector_returns_nothing_for_the_empty_set(self, atlas) -> None:  # type: ignore[no-untyped-def]
        organization_id = atlas.organization.id
        leaked = []
        for name, fn in public_selectors():
            if "limit_to_site_ids" not in inspect.signature(fn).parameters:
                continue
            result = self._call(fn, organization_id, set())
            if result is None:
                continue
            if not self._emptiness(result):
                leaked.append(f"{name} -> {result!r}"[:200])
        assert not leaked, (
            "These selectors widened an EMPTY site scope into results. The empty set means "
            "no sites, never 'no filter':\n  " + "\n  ".join(leaked)
        )

    def test_the_same_selectors_do_return_data_when_scope_is_none(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Non-vacuity control: prove the emptiness check can distinguish the two cases."""
        organization_id = atlas.organization.id
        produced_something = False
        for _name, fn in public_selectors():
            if "limit_to_site_ids" not in inspect.signature(fn).parameters:
                continue
            result = self._call(fn, organization_id, None)
            if result is not None and not self._emptiness(result):
                produced_something = True
        assert produced_something, (
            "No scoped selector returned data for a tenant-wide scope, so the empty-set "
            "assertion above proves nothing."
        )


class TestEffectiveSiteScopeFailsClosed:
    """Tenant-wide visibility is an allowlist, never a subtraction.

    The retired implementation computed `active_roles - {SUPERVISOR}` and returned `None`
    (tenant-wide) if anything survived. Any role token the codebase did not recognise
    survived that subtraction -- a value written straight to the database, a role added to
    the enum but not to the table, a typo in a fixture -- and silently widened the reader
    to the whole tenant. An intersection with a named allowlist fails closed instead.
    """

    @pytest.fixture
    def atlas(self, settings):  # type: ignore[no-untyped-def]
        settings.APP_ENV = "local"
        return loaded_atlas()

    @staticmethod
    def _add_role(membership, role: str) -> None:  # type: ignore[no-untyped-def]
        from apps.organizations.models import MembershipRoleGrant

        MembershipRoleGrant.objects.create(membership=membership, role=role, revoked_at=None)

    @pytest.mark.parametrize("who", ["owner", "ops", "finance", "auditor"])
    def test_the_four_allowlisted_roles_are_tenant_wide(self, atlas, who) -> None:  # type: ignore[no-untyped-def]
        from apps.organizations.policy import effective_site_scope

        assert effective_site_scope(getattr(atlas, who)) is None

    def test_supervisor_only_is_never_tenant_wide(self, atlas) -> None:  # type: ignore[no-untyped-def]
        from apps.organizations.policy import effective_site_scope

        assert effective_site_scope(atlas.supervisor) == set()

    def test_an_unknown_role_alone_is_never_tenant_wide(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """The case the subtraction got wrong."""
        from apps.organizations.models import MembershipRoleGrant
        from apps.organizations.policy import effective_site_scope

        MembershipRoleGrant.objects.filter(membership=atlas.supervisor).delete()
        self._add_role(atlas.supervisor, "regional_director")
        atlas.supervisor.refresh_from_db()
        assert "regional_director" in atlas.supervisor.active_roles, "precondition"

        scope = effective_site_scope(atlas.supervisor)
        assert scope is not None, "an unrecognised role widened the reader to the whole tenant"
        assert scope == set()

    def test_supervisor_plus_an_unknown_role_is_never_tenant_wide(self, atlas) -> None:  # type: ignore[no-untyped-def]
        from apps.organizations.policy import effective_site_scope

        self._add_role(atlas.supervisor, "regional_director")
        atlas.supervisor.refresh_from_db()
        scope = effective_site_scope(atlas.supervisor)
        assert scope is not None, "supervisor + an unknown token widened to the whole tenant"
        assert scope == set()

    def test_an_unknown_role_still_honours_explicit_grants(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Failing closed must narrow to the grants, not erase them."""
        from apps.operations.models import Site
        from apps.organizations.models import MembershipSiteGrant
        from apps.organizations.policy import effective_site_scope

        site = Site.objects.filter(organization=atlas.organization).first()
        MembershipSiteGrant.objects.create(membership=atlas.supervisor, site=site)
        self._add_role(atlas.supervisor, "regional_director")
        atlas.supervisor.refresh_from_db()
        assert effective_site_scope(atlas.supervisor) == {site.id}

    def test_an_unknown_role_grants_no_action(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Deny-by-default at the action layer too, not only at the scope layer."""
        from apps.organizations.models import MembershipRoleGrant
        from apps.organizations.policy import allows
        from apps.organizations.roles import Action

        MembershipRoleGrant.objects.filter(membership=atlas.supervisor).delete()
        self._add_role(atlas.supervisor, "regional_director")
        atlas.supervisor.refresh_from_db()
        for action in (Action.VIEW_ORGANIZATION, Action.ACT_ON_CASE, Action.EXPORT_FINANCE_CSV):
            assert not allows(atlas.supervisor, action), action


class TestSiteScopedActionsIsHonest:
    """Requirement 6: the matrix must not claim an enforcement that does not exist."""

    def test_resolve_operational_reconciliation_is_no_longer_declared_site_scoped(self) -> None:
        from apps.organizations.roles import ACTION_ROLES, SITE_SCOPED_ACTIONS, Action, Role

        assert Action.RESOLVE_OPERATIONAL_RECONCILIATION not in SITE_SCOPED_ACTIONS
        assert Role.SUPERVISOR not in ACTION_ROLES[Action.RESOLVE_OPERATIONAL_RECONCILIATION], (
            "supervisors must not gain mutation authority over reconciliation"
        )

    def test_act_on_case_remains_declared_as_the_future_contract(self) -> None:
        from apps.organizations.roles import SITE_SCOPED_ACTIONS, Action

        assert Action.ACT_ON_CASE in SITE_SCOPED_ACTIONS

    def test_tenant_wide_roles_is_an_explicit_allowlist(self) -> None:
        from apps.organizations.roles import TENANT_WIDE_ROLES, Role

        assert TENANT_WIDE_ROLES == frozenset(
            {Role.OWNER, Role.OPERATIONS_MANAGER, Role.FINANCE_REVIEWER, Role.AUDITOR}
        )
        assert Role.SUPERVISOR not in TENANT_WIDE_ROLES
