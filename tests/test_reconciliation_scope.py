"""Reconciliation visibility and resolution authority (Phase 2.1).

Two separate properties are tested here, and they fail in different directions.

**Visibility.** A supervisor may read only non-financial issues whose canonical subject
resolves unambiguously to a site they were granted. A reconciliation issue names exactly
one typed subject; only `site` and `work_order` identify a single site. Customer-wide,
contract-wide, obligation-wide and financial subjects stay hidden, because attributing
them to one granted site would be a guess.

**Authority ordering.** Resolution must never let the response distinguish "this issue
does not exist" from "this issue exists but is not yours to resolve". A 403 that only
appears for real ids is an existence oracle, and reconciliation issues name real customers
and sites.
"""

from __future__ import annotations

import uuid

import pytest
from django.urls import reverse

from apps.ingestion import selectors
from apps.ingestion.models import (
    FINANCIAL_FIELD_GROUPS,
    OPERATIONAL_FIELD_GROUPS,
    ReconciliationIssue,
    SourcePrecedenceRule,
)
from apps.operations.models import Site
from apps.organizations.models import MembershipSiteGrant, User
from tests.phase6_helpers import loaded_atlas

pytestmark = pytest.mark.django_db


@pytest.fixture
def atlas(settings):  # type: ignore[no-untyped-def]
    settings.APP_ENV = "local"
    return loaded_atlas()


def make_issue(atlas, *, field_group: str, entity_type: str, subject) -> ReconciliationIssue:  # type: ignore[no-untyped-def]
    return ReconciliationIssue.objects.create(
        organization=atlas.organization,
        field_group=field_group,
        entity_type=entity_type,
        status=ReconciliationIssue.Status.OPEN,
        is_blocking=False,
        explanation=f"Synthetic {field_group} conflict for scope testing.",
        **{entity_type: subject},
    )


@pytest.fixture
def issues(atlas):  # type: ignore[no-untyped-def]
    """One issue per subject shape, all in the granted site's blast radius or not."""
    work_order = atlas.item.work_order
    granted_site = work_order.site
    other_site = (
        Site.objects.filter(organization=atlas.organization).exclude(id=granted_site.id).first()
    )
    return {
        "site_granted": make_issue(
            atlas, field_group="completion", entity_type="site", subject=granted_site
        ),
        "site_other": make_issue(
            atlas, field_group="completion", entity_type="site", subject=other_site
        ),
        "work_order_granted": make_issue(
            atlas, field_group="schedule_status", entity_type="work_order", subject=work_order
        ),
        "customer_wide": make_issue(
            atlas, field_group="identity", entity_type="customer", subject=work_order.customer
        ),
        "contract_wide": make_issue(
            atlas, field_group="identity", entity_type="contract", subject=work_order.contract
        ),
        "financial_on_granted_site": make_issue(
            atlas, field_group="contract_rate", entity_type="site", subject=granted_site
        ),
    }


def grant(atlas, site):  # type: ignore[no-untyped-def]
    MembershipSiteGrant.objects.create(membership=atlas.supervisor, site=site)


class TestTheDomainSplitIsExhaustive:
    def test_every_field_group_falls_on_exactly_one_side(self) -> None:
        declared = {value for value, _ in SourcePrecedenceRule.FieldGroup.choices}
        assert FINANCIAL_FIELD_GROUPS | OPERATIONAL_FIELD_GROUPS == declared, (
            "a FieldGroup value is on neither side of the finance boundary; adding one "
            "must be a deliberate decision, not a default"
        )
        assert not (FINANCIAL_FIELD_GROUPS & OPERATIONAL_FIELD_GROUPS)


class TestSupervisorVisibility:
    """Requirement 1."""

    def _visible(self, atlas):  # type: ignore[no-untyped-def]
        return set(
            selectors.open_reconciliation_issues_for(atlas.supervisor).values_list("id", flat=True)
        )

    def test_zero_grants_sees_no_issues_at_all(self, atlas, issues) -> None:  # type: ignore[no-untyped-def]
        assert self._visible(atlas) == set()

    def test_a_granted_site_reveals_only_that_sites_non_financial_issues(
        self, atlas, issues
    ) -> None:  # type: ignore[no-untyped-def]
        grant(atlas, atlas.item.work_order.site)
        visible = self._visible(atlas)
        assert issues["site_granted"].id in visible
        assert issues["work_order_granted"].id in visible, (
            "a work order resolves unambiguously to one site and must be visible"
        )
        assert issues["site_other"].id not in visible
        assert issues["customer_wide"].id not in visible, "customer-wide is not one site"
        assert issues["contract_wide"].id not in visible, "contract-wide is not one site"
        assert issues["financial_on_granted_site"].id not in visible, (
            "a finance conflict is never a supervisor's, at any site"
        )
        assert len(visible) == 2

    def test_a_different_grant_reveals_nothing_of_the_first_site(self, atlas, issues) -> None:  # type: ignore[no-untyped-def]
        other = (
            Site.objects.filter(organization=atlas.organization)
            .exclude(id=atlas.item.work_order.site_id)
            .first()
        )
        grant(atlas, other)
        visible = self._visible(atlas)
        assert issues["site_other"].id in visible
        assert issues["site_granted"].id not in visible
        assert issues["work_order_granted"].id not in visible


class TestTenantWideReadersAreUnchanged:
    """Requirement 2 -- this correction must not narrow anybody else."""

    @pytest.mark.parametrize("who", ["owner", "ops", "finance", "auditor"])
    def test_every_tenant_wide_role_still_sees_all_six(self, atlas, issues, who) -> None:  # type: ignore[no-untyped-def]
        membership = getattr(atlas, who)
        visible = selectors.open_reconciliation_issues_for(membership)
        assert visible.count() == len(issues) == 6


class TestEverySurfaceAgrees:
    """Requirement 3 -- the badge count, the queue list and the links use one scope."""

    def _get(self, client, email, url):  # type: ignore[no-untyped-def]
        client.force_login(User.objects.get(email=email))
        response = client.get(url)
        assert response.status_code == 200
        return response

    def test_the_badge_count_matches_what_the_queue_lists(self, atlas, issues, client) -> None:  # type: ignore[no-untyped-def]
        grant(atlas, atlas.item.work_order.site)
        imports = self._get(client, "supervisor@atlas.example", reverse("ingestion:import-list"))
        assert imports.context["open_reconciliation_issues"] == 2
        queue = self._get(
            client, "supervisor@atlas.example", reverse("ingestion:reconciliation-queue")
        )
        assert len(list(queue.context["issues"])) == 2

    def test_a_zero_grant_supervisor_sees_zero_on_both(self, atlas, issues, client) -> None:  # type: ignore[no-untyped-def]
        imports = self._get(client, "supervisor@atlas.example", reverse("ingestion:import-list"))
        assert imports.context["open_reconciliation_issues"] == 0
        queue = self._get(
            client, "supervisor@atlas.example", reverse("ingestion:reconciliation-queue")
        )
        assert list(queue.context["issues"]) == []
        body = queue.content.decode()
        for issue in issues.values():
            assert str(issue.id) not in body

    def test_the_owner_sees_six_on_both(self, atlas, issues, client) -> None:  # type: ignore[no-untyped-def]
        """Non-vacuity control for the two tests above."""
        imports = self._get(client, "owner@atlas.example", reverse("ingestion:import-list"))
        assert imports.context["open_reconciliation_issues"] == 6
        queue = self._get(client, "owner@atlas.example", reverse("ingestion:reconciliation-queue"))
        assert len(list(queue.context["issues"])) == 6

    def test_the_supervisor_is_offered_no_resolve_control(self, atlas, issues, client) -> None:  # type: ignore[no-untyped-def]
        grant(atlas, atlas.item.work_order.site)
        queue = self._get(
            client, "supervisor@atlas.example", reverse("ingestion:reconciliation-queue")
        )
        assert queue.context["can_resolve_operational"] is False
        assert queue.context["can_resolve_financial"] is False


class TestResolutionAuthorityOrdering:
    """Requirement 4. The response must never confirm that an id exists."""

    def _post(self, client, email, issue_id):  # type: ignore[no-untyped-def]
        client.force_login(User.objects.get(email=email))
        return client.post(
            reverse("ingestion:reconciliation-resolve", kwargs={"issue_id": issue_id})
        )

    def test_no_resolution_authority_is_denied_before_lookup(self, atlas, issues, client) -> None:  # type: ignore[no-untyped-def]
        """A supervisor and an auditor hold neither resolve action."""
        grant(atlas, atlas.item.work_order.site)
        for email in ("supervisor@atlas.example", "auditor@atlas.example"):
            real = self._post(client, email, issues["site_granted"].id)
            fake = self._post(client, email, uuid.uuid4())
            assert real.status_code == 403, email
            assert fake.status_code == 403, email
            assert real.status_code == fake.status_code, (
                f"{email} can tell a real issue id from an invented one"
            )

    def test_an_unauthorized_domain_is_indistinguishable_from_a_nonexistent_id(
        self, atlas, issues, client
    ) -> None:  # type: ignore[no-untyped-def]
        """An operations manager may resolve operational conflicts, never financial ones."""
        financial = self._post(client, "ops@atlas.example", issues["financial_on_granted_site"].id)
        nonexistent = self._post(client, "ops@atlas.example", uuid.uuid4())
        assert financial.status_code == 404
        assert nonexistent.status_code == 404
        assert financial.content == nonexistent.content

    def test_the_mirror_case_for_finance(self, atlas, issues, client) -> None:  # type: ignore[no-untyped-def]
        operational = self._post(client, "finance@atlas.example", issues["site_granted"].id)
        nonexistent = self._post(client, "finance@atlas.example", uuid.uuid4())
        assert operational.status_code == 404
        assert nonexistent.status_code == 404

    def test_a_cross_tenant_id_is_also_indistinguishable(self, atlas, issues, client) -> None:  # type: ignore[no-untyped-def]
        from apps.organizations.models import Membership, Organization

        beacon = Organization.objects.get(slug="beacon-building-care")
        owner = Membership.objects.get(organization=beacon, user__email="owner@beacon.example")
        assert owner  # precondition
        foreign = self._post(client, "owner@beacon.example", issues["site_granted"].id)
        nonexistent = self._post(client, "owner@beacon.example", uuid.uuid4())
        assert foreign.status_code == nonexistent.status_code == 404

    def test_the_authorized_path_still_works(self, atlas, issues, client) -> None:  # type: ignore[no-untyped-def]
        """Non-vacuity: the ordering must not have broken resolution itself."""
        response = self._post(client, "ops@atlas.example", issues["site_granted"].id)
        assert response.status_code == 302
        issues["site_granted"].refresh_from_db()
        assert issues["site_granted"].status == ReconciliationIssue.Status.RESOLVED

    def test_finance_can_still_resolve_a_financial_issue(self, atlas, issues, client) -> None:  # type: ignore[no-untyped-def]
        response = self._post(
            client, "finance@atlas.example", issues["financial_on_granted_site"].id
        )
        assert response.status_code == 302
        issues["financial_on_granted_site"].refresh_from_db()
        assert issues["financial_on_granted_site"].status == ReconciliationIssue.Status.RESOLVED

    def test_a_supervisor_can_never_resolve_even_a_granted_site_issue(
        self, atlas, issues, client
    ) -> None:  # type: ignore[no-untyped-def]
        """Requirement 6: view-only. The read widened; the mutation did not."""
        grant(atlas, atlas.item.work_order.site)
        assert issues["site_granted"].id in set(
            selectors.open_reconciliation_issues_for(atlas.supervisor).values_list("id", flat=True)
        ), "precondition: the supervisor really can see this issue"
        response = self._post(client, "supervisor@atlas.example", issues["site_granted"].id)
        assert response.status_code == 403
        issues["site_granted"].refresh_from_db()
        assert issues["site_granted"].status == ReconciliationIssue.Status.OPEN
