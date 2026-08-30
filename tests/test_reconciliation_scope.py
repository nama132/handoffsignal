"""Reconciliation visibility and resolution authority (Phase 2.1).

Two separate properties are tested here, and they fail in different directions.

**Visibility.** A supervisor may read only non-financial issues whose canonical subject
resolves unambiguously to a site they were granted. A reconciliation issue names exactly
one typed subject, and which of the seven resolve to a single site is a fact about the
schema, not a judgement:

* `site`, `work_order` and `service_obligation` each reach exactly one site through
  single-valued foreign keys -- an obligation via `contract_site`, which names one site.
  A supervisor granted that site sees them.
* `customer` and `contract` reach their sites through multi-valued relations and may
  cover several, so they stay hidden rather than being attributed by guess.
* `accounting_invoice` and `accounting_payment` do each resolve to one site, but are
  deliberately still hidden: an accounting record is finance-domain by virtue of what
  it is, and a supervisor holds no finance role. That is a settled product-policy
  boundary rather than a schema limit, and it is asserted below so it cannot erode by
  accident.

All seven subject types are represented in the fixture.

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
    """One open issue per subject shape, covering all seven typed subjects.

    `granted` in a key means the subject sits at the site the supervisor is granted in
    these tests (Meridian Business Center); `other` means a different site.
    """
    from apps.operations.models import AccountingInvoice, AccountingPayment, ServiceObligation

    work_order = atlas.item.work_order
    granted_site = work_order.site
    other_site = (
        Site.objects.filter(organization=atlas.organization).exclude(id=granted_site.id).first()
    )

    obligation_granted = ServiceObligation.objects.filter(
        organization=atlas.organization, contract_site__site=granted_site
    ).first()
    obligation_other = ServiceObligation.objects.filter(
        organization=atlas.organization, contract_site__site=other_site
    ).first()
    invoice_granted = AccountingInvoice.objects.filter(
        organization=atlas.organization, site=granted_site
    ).first()
    payment_granted = AccountingPayment.objects.filter(
        organization=atlas.organization, accounting_invoice__site=granted_site
    ).first()

    # Preconditions. An absent fixture object would make a hidden-ness assertion pass for
    # entirely the wrong reason.
    assert obligation_granted is not None and obligation_other is not None
    assert obligation_granted.contract_site.site_id == granted_site.id
    assert obligation_other.contract_site.site_id == other_site.id
    assert invoice_granted is not None and payment_granted is not None

    return {
        # --- resolves to exactly one site --------------------------------------------
        "site_granted": make_issue(
            atlas, field_group="completion", entity_type="site", subject=granted_site
        ),
        "site_other": make_issue(
            atlas, field_group="completion", entity_type="site", subject=other_site
        ),
        "work_order_granted": make_issue(
            atlas, field_group="schedule_status", entity_type="work_order", subject=work_order
        ),
        "obligation_granted": make_issue(
            atlas,
            field_group="completion",
            entity_type="service_obligation",
            subject=obligation_granted,
        ),
        "obligation_other": make_issue(
            atlas,
            field_group="completion",
            entity_type="service_obligation",
            subject=obligation_other,
        ),
        # --- reaches several sites, so cannot be attributed to one ---------------------
        "customer_wide": make_issue(
            atlas, field_group="identity", entity_type="customer", subject=work_order.customer
        ),
        "contract_wide": make_issue(
            atlas, field_group="identity", entity_type="contract", subject=work_order.contract
        ),
        # --- resolves to one site, but is finance's to see -----------------------------
        "accounting_invoice_operational": make_issue(
            atlas,
            field_group="identity",
            entity_type="accounting_invoice",
            subject=invoice_granted,
        ),
        "accounting_payment_operational": make_issue(
            atlas,
            field_group="identity",
            entity_type="accounting_payment",
            subject=payment_granted,
        ),
        # --- a financial field group, at the granted site -------------------------------
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
        assert issues["obligation_granted"].id in visible, (
            "a service obligation reaches exactly one site through contract_site and must "
            "be visible to a supervisor granted that site"
        )
        assert issues["site_other"].id not in visible
        assert issues["obligation_other"].id not in visible
        assert issues["customer_wide"].id not in visible, "a customer may hold many sites"
        assert issues["contract_wide"].id not in visible, "a contract may cover many sites"
        assert issues["financial_on_granted_site"].id not in visible, (
            "a finance conflict is never a supervisor's, at any site"
        )
        assert len(visible) == 3

    def test_a_different_grant_reveals_nothing_of_the_first_site(self, atlas, issues) -> None:  # type: ignore[no-untyped-def]
        other = (
            Site.objects.filter(organization=atlas.organization)
            .exclude(id=atlas.item.work_order.site_id)
            .first()
        )
        grant(atlas, other)
        visible = self._visible(atlas)
        assert issues["site_other"].id in visible
        assert issues["obligation_other"].id in visible
        assert issues["site_granted"].id not in visible
        assert issues["work_order_granted"].id not in visible
        assert issues["obligation_granted"].id not in visible


class TestServiceObligationSiteResolution:
    """A service obligation resolves to exactly one site, so it is scopeable.

    `ServiceObligation.contract_site` is a single foreign key to `ContractSite`, which
    names one `site`. An obligation therefore belongs to one contract-site period, never
    to a contract as a whole -- an earlier revision of this module wrongly described it as
    "obligation-wide" and hid it from every supervisor, which denied a granted supervisor
    a conflict that was genuinely theirs. These five tests pin the behaviour down.
    """

    def _visible(self, atlas):  # type: ignore[no-untyped-def]
        return set(
            selectors.open_reconciliation_issues_for(atlas.supervisor).values_list("id", flat=True)
        )

    def test_the_obligation_really_does_resolve_to_one_site(self, atlas, issues) -> None:  # type: ignore[no-untyped-def]
        """Precondition, asserted rather than assumed: the path is single-valued."""
        obligation = issues["obligation_granted"].service_obligation
        assert obligation is not None
        assert obligation.contract_site.site_id == atlas.item.work_order.site_id

    def test_a_supervisor_granted_the_obligations_site_sees_it(self, atlas, issues) -> None:  # type: ignore[no-untyped-def]
        grant(atlas, atlas.item.work_order.site)
        assert issues["obligation_granted"].id in self._visible(atlas)

    def test_a_supervisor_granted_another_site_does_not_see_it(self, atlas, issues) -> None:  # type: ignore[no-untyped-def]
        other = (
            Site.objects.filter(organization=atlas.organization)
            .exclude(id=atlas.item.work_order.site_id)
            .first()
        )
        grant(atlas, other)
        visible = self._visible(atlas)
        assert issues["obligation_granted"].id not in visible
        assert issues["obligation_other"].id in visible, (
            "non-vacuity: the other site's obligation must be visible to this grant"
        )

    def test_a_supervisor_with_no_grants_does_not_see_it(self, atlas, issues) -> None:  # type: ignore[no-untyped-def]
        assert self._visible(atlas) == set()

    @pytest.mark.parametrize("who", ["owner", "ops", "finance", "auditor"])
    def test_tenant_wide_roles_continue_to_see_it(self, atlas, issues, who) -> None:  # type: ignore[no-untyped-def]
        visible = set(
            selectors.open_reconciliation_issues_for(getattr(atlas, who)).values_list(
                "id", flat=True
            )
        )
        assert issues["obligation_granted"].id in visible
        assert issues["obligation_other"].id in visible

    def test_a_financial_obligation_issue_stays_hidden_from_a_granted_supervisor(
        self, atlas
    ) -> None:  # type: ignore[no-untyped-def]
        """Site resolution widens the subject, never the finance boundary."""
        from apps.operations.models import ServiceObligation

        granted_site = atlas.item.work_order.site
        obligation = ServiceObligation.objects.filter(
            organization=atlas.organization, contract_site__site=granted_site
        ).first()
        financial = make_issue(
            atlas,
            field_group="contract_rate",
            entity_type="service_obligation",
            subject=obligation,
        )
        grant(atlas, granted_site)
        assert financial.id not in self._visible(atlas)


class TestAllSevenSubjectTypesAreCovered:
    """Requirement 3: the fixture must exercise every typed subject, not a convenient few."""

    def test_the_fixture_represents_every_declared_subject(self, atlas, issues) -> None:  # type: ignore[no-untyped-def]
        from apps.ingestion.models import TARGET_FIELDS

        represented = {issue.entity_type for issue in issues.values()}
        assert represented == set(TARGET_FIELDS), (
            f"missing subject types: {sorted(set(TARGET_FIELDS) - represented)}"
        )

    def test_each_issue_names_exactly_one_subject(self, atlas, issues) -> None:  # type: ignore[no-untyped-def]
        from apps.ingestion.models import TARGET_FIELDS

        for key, issue in issues.items():
            populated = [f for f in TARGET_FIELDS if getattr(issue, f"{f}_id", None) is not None]
            assert populated == [issue.entity_type], f"{key}: {populated}"


class TestAccountingSubjectsRemainHidden:
    """A settled product-policy boundary, not a schema limit -- so it cannot erode.

    `AccountingInvoice.site` is a single foreign key, and a payment reaches a site through
    its invoice, so both DO resolve unambiguously to one site. They are nonetheless not
    matched by the site filter: a supervisor holds no finance role, and an issue whose
    subject is an accounting record is finance's to see even when its field group is
    operational. The owner has settled that boundary: the domain of the subject decides,
    not the domain of the field group, and no selector branch is to be added for either.
    """

    def _visible(self, atlas):  # type: ignore[no-untyped-def]
        return set(
            selectors.open_reconciliation_issues_for(atlas.supervisor).values_list("id", flat=True)
        )

    def test_the_paths_would_resolve_if_we_chose_to_use_them(self, atlas, issues) -> None:  # type: ignore[no-untyped-def]
        """The reason for hiding them is policy, not an inability to scope them."""
        from apps.ingestion.models import ReconciliationIssue

        site_id = atlas.item.work_order.site_id
        assert ReconciliationIssue.objects.filter(
            id=issues["accounting_invoice_operational"].id, accounting_invoice__site_id=site_id
        ).exists()
        assert ReconciliationIssue.objects.filter(
            id=issues["accounting_payment_operational"].id,
            accounting_payment__accounting_invoice__site_id=site_id,
        ).exists()

    def test_but_a_granted_supervisor_still_does_not_see_them(self, atlas, issues) -> None:  # type: ignore[no-untyped-def]
        grant(atlas, atlas.item.work_order.site)
        visible = self._visible(atlas)
        assert issues["accounting_invoice_operational"].id not in visible
        assert issues["accounting_payment_operational"].id not in visible
        assert issues["obligation_granted"].id in visible, "non-vacuity: scoping does work"


class TestTenantWideReadersAreUnchanged:
    """Requirement 2 -- this correction must not narrow anybody else."""

    @pytest.mark.parametrize("who", ["owner", "ops", "finance", "auditor"])
    def test_every_tenant_wide_role_still_sees_every_issue(self, atlas, issues, who) -> None:  # type: ignore[no-untyped-def]
        membership = getattr(atlas, who)
        visible = selectors.open_reconciliation_issues_for(membership)
        assert visible.count() == len(issues) == 10


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
        assert imports.context["open_reconciliation_issues"] == 3
        queue = self._get(
            client, "supervisor@atlas.example", reverse("ingestion:reconciliation-queue")
        )
        assert len(list(queue.context["issues"])) == 3

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

    def test_the_owner_sees_all_ten_on_both(self, atlas, issues, client) -> None:  # type: ignore[no-untyped-def]
        """Non-vacuity control for the two tests above."""
        imports = self._get(client, "owner@atlas.example", reverse("ingestion:import-list"))
        assert imports.context["open_reconciliation_issues"] == 10
        queue = self._get(client, "owner@atlas.example", reverse("ingestion:reconciliation-queue"))
        assert len(list(queue.context["issues"])) == 10

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
