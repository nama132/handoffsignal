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
    "apps.ingestion.selectors.open_reconciliation_issues": "OPEN PRODUCT DECISION. Unlike an identity issue, a ReconciliationIssue names a "
    "typed canonical subject that CAN be a site or a work order, so it is genuinely "
    "site-addressable. It is currently rendered organization-wide to any reader with "
    "VIEW_ORGANIZATION. Left unscoped pending an explicit owner decision, because "
    "scoping it is a product question about who owns reconciliation, not a bug fix.",
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
