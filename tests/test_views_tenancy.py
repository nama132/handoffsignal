"""View-layer tenancy and authorization.

Phase 2's user-visible proof (line 2461): "Log in as users from two synthetic
organizations. Show that each sees only its own organization shell and that direct
cross-tenant URLs fail safely."
"""

from __future__ import annotations

import uuid

import pytest
from django.urls import reverse

from apps.organizations.context import SESSION_ORGANIZATION_KEY
from apps.organizations.roles import Role
from tests.factories import (
    CustomerAccountFactory,
    MembershipFactory,
    MembershipSiteGrantFactory,
    SiteFactory,
    UserFactory,
    make_tenant,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenants():  # type: ignore[no-untyped-def]
    from types import SimpleNamespace

    a = make_tenant("acme-clean", roles=(Role.OWNER,))
    b = make_tenant("borough-clean", roles=(Role.OWNER,))
    for tenant in (a, b):
        tenant.user.set_password("pw-for-tests-only")
        tenant.user.save()
    return SimpleNamespace(a=a, b=b)


class TestOrganizationShellIsolation:
    def test_each_user_sees_only_their_own_organization(self, client, tenants) -> None:  # type: ignore[no-untyped-def]
        client.force_login(tenants.a.user)
        response = client.get(reverse("app:organization"))
        assert response.status_code == 200
        body = response.content.decode()
        assert tenants.a.organization.display_name in body
        assert tenants.b.organization.display_name not in body

    def test_neighbour_records_never_appear(self, client, tenants) -> None:  # type: ignore[no-untyped-def]
        CustomerAccountFactory(organization=tenants.b.organization, name="Neighbour Secret Ltd")
        client.force_login(tenants.a.user)
        body = client.get(reverse("app:organization")).content.decode()
        assert "Neighbour Secret Ltd" not in body
        assert tenants.a.customer.name in body

    def test_cockpit_and_organization_page_both_name_the_tenant(self, client, tenants) -> None:  # type: ignore[no-untyped-def]
        client.force_login(tenants.a.user)
        for name in ("app:home", "app:organization"):
            body = client.get(reverse(name)).content.decode()
            assert tenants.a.organization.display_name in body
            assert tenants.b.organization.display_name not in body


class TestCrossTenantSessionTampering:
    def test_a_forged_session_organization_is_not_honoured(self, client, tenants) -> None:  # type: ignore[no-untyped-def]
        """The session value is a candidate, never an authorization."""
        client.force_login(tenants.a.user)
        session = client.session
        session[SESSION_ORGANIZATION_KEY] = str(tenants.b.organization.id)
        session.save()
        response = client.get(reverse("app:home"))
        body = response.content.decode()
        assert tenants.b.organization.display_name not in body
        # It falls back to A's own single membership rather than granting B.
        assert tenants.a.organization.display_name in body

    def test_a_garbage_session_value_is_discarded(self, client, tenants) -> None:  # type: ignore[no-untyped-def]
        client.force_login(tenants.a.user)
        session = client.session
        session[SESSION_ORGANIZATION_KEY] = "not-a-uuid"
        session.save()
        assert client.get(reverse("app:home")).status_code == 200

    def test_posting_another_tenants_id_to_select_organization_fails(self, client, tenants) -> None:  # type: ignore[no-untyped-def]
        client.force_login(tenants.a.user)
        response = client.post(
            reverse("organizations:select-organization"),
            {"organization_id": str(tenants.b.organization.id)},
        )
        assert response.status_code == 404
        assert client.session.get(SESSION_ORGANIZATION_KEY) != str(tenants.b.organization.id)

    def test_unknown_organization_id_looks_identical_to_a_foreign_one(
        self, client, tenants
    ) -> None:  # type: ignore[no-untyped-def]
        """Membership elsewhere must not be disclosed by a different status code."""
        client.force_login(tenants.a.user)
        foreign = client.post(
            reverse("organizations:select-organization"),
            {"organization_id": str(tenants.b.organization.id)},
        )
        nonexistent = client.post(
            reverse("organizations:select-organization"),
            {"organization_id": str(uuid.uuid4())},
        )
        assert foreign.status_code == nonexistent.status_code == 404


class TestOrganizationSelection:
    def test_single_membership_is_selected_implicitly(self, client, tenants) -> None:  # type: ignore[no-untyped-def]
        client.force_login(tenants.a.user)
        assert client.get(reverse("app:home")).status_code == 200

    def test_multiple_memberships_require_a_choice(self, client) -> None:  # type: ignore[no-untyped-def]
        user = UserFactory(email="multi@example.test")
        first = make_tenant("multi-one")
        second = make_tenant("multi-two")
        MembershipFactory(organization=first.organization, user=user, roles=[Role.OWNER])
        MembershipFactory(organization=second.organization, user=user, roles=[Role.OWNER])
        client.force_login(user)
        response = client.get(reverse("app:home"))
        assert response.status_code == 302
        assert reverse("organizations:select-organization") in response.url

    def test_choosing_an_organization_then_reaching_the_shell(self, client) -> None:  # type: ignore[no-untyped-def]
        user = UserFactory(email="chooser@example.test")
        first = make_tenant("choose-one")
        second = make_tenant("choose-two")
        MembershipFactory(organization=first.organization, user=user, roles=[Role.OWNER])
        MembershipFactory(organization=second.organization, user=user, roles=[Role.OWNER])
        client.force_login(user)
        response = client.post(
            reverse("organizations:select-organization"),
            {"organization_id": str(second.organization.id)},
        )
        assert response.status_code == 302
        body = client.get(reverse("app:organization")).content.decode()
        assert second.organization.display_name in body
        assert first.organization.display_name not in body

    def test_user_with_no_membership_sees_an_explanation(self, client) -> None:  # type: ignore[no-untyped-def]
        user = UserFactory(email="orphan@example.test")
        client.force_login(user)
        response = client.get(reverse("organizations:select-organization"))
        assert response.status_code == 200
        assert b"no active organization membership" in response.content

    def test_selection_requires_authentication(self, client) -> None:  # type: ignore[no-untyped-def]
        response = client.get(reverse("organizations:select-organization"))
        assert response.status_code == 302
        assert reverse("login") in response.url

    def test_missing_organization_id_is_a_bad_request(self, client, tenants) -> None:  # type: ignore[no-untyped-def]
        client.force_login(tenants.a.user)
        response = client.post(reverse("organizations:select-organization"), {})
        assert response.status_code == 400


class TestAccessRevocation:
    def test_deactivated_membership_loses_access_on_the_next_request(self, client, tenants) -> None:  # type: ignore[no-untyped-def]
        client.force_login(tenants.a.user)
        assert client.get(reverse("app:home")).status_code == 200
        tenants.a.membership.is_active = False
        tenants.a.membership.save()
        response = client.get(reverse("app:home"))
        assert response.status_code == 302
        assert reverse("organizations:select-organization") in response.url

    def test_suspended_organization_loses_access_on_the_next_request(self, client, tenants) -> None:  # type: ignore[no-untyped-def]
        client.force_login(tenants.a.user)
        assert client.get(reverse("app:home")).status_code == 200
        tenants.a.organization.status = "suspended"
        tenants.a.organization.save()
        assert client.get(reverse("app:home")).status_code == 302

    def test_membership_without_a_role_grant_is_refused(self, client) -> None:  # type: ignore[no-untyped-def]
        user = UserFactory(email="norole@example.test")
        tenant = make_tenant("no-role-org")
        MembershipFactory(organization=tenant.organization, user=user)  # no roles
        client.force_login(user)
        response = client.get(reverse("app:home"))
        assert response.status_code == 403


class TestCsrfAndMethods:
    def test_select_organization_requires_csrf(self, tenants) -> None:  # type: ignore[no-untyped-def]
        from django.test import Client

        enforcing = Client(enforce_csrf_checks=True)
        enforcing.force_login(tenants.a.user)
        response = enforcing.post(
            reverse("organizations:select-organization"),
            {"organization_id": str(tenants.a.organization.id)},
        )
        assert response.status_code == 403

    def test_shell_rejects_unsupported_methods(self, client, tenants) -> None:  # type: ignore[no-untyped-def]
        client.force_login(tenants.a.user)
        assert client.delete(reverse("organizations:select-organization")).status_code == 405


class TestPermissionAwareRendering:
    """These inspect the organization page, where customers, sites and permissions render."""

    def test_owner_sees_management_permissions_as_permitted(self, client, tenants) -> None:  # type: ignore[no-untyped-def]
        client.force_login(tenants.a.user)
        body = client.get(reverse("app:organization")).content.decode()
        assert "Manage memberships and roles" in body
        assert "Permitted" in body

    def test_auditor_sees_them_as_not_permitted(self, client) -> None:  # type: ignore[no-untyped-def]
        tenant = make_tenant("auditor-org", roles=(Role.AUDITOR,))
        client.force_login(tenant.user)
        body = client.get(reverse("app:organization")).content.decode()
        assert "Not permitted" in body

    def test_supervisor_with_no_grants_sees_no_site_or_customer_names(self, client) -> None:  # type: ignore[no-untyped-def]
        """Assert on rendered identifiers, not on explanatory copy.

        The earlier version of this test asserted only that a sentence appeared, so it
        passed while the page listed every site in the organization. It now proves the
        claim: with zero grants, neither the site name nor its customer's name is
        rendered anywhere.
        """
        tenant = make_tenant("supervisor-zero", roles=(Role.SUPERVISOR,))
        tenant.site.name = "Zero Grant Tower"
        tenant.site.save()
        tenant.customer.name = "Zero Grant Holdings"
        tenant.customer.save()
        client.force_login(tenant.user)
        body = client.get(reverse("app:organization")).content.decode()
        assert "Zero Grant Tower" not in body
        assert "Zero Grant Holdings" not in body

    def test_supervisor_sees_a_granted_site_but_not_an_ungranted_one(self, client) -> None:  # type: ignore[no-untyped-def]
        """The decisive case: one granted site, one not, in the same organization."""
        tenant = make_tenant("supervisor-partial", roles=(Role.SUPERVISOR,))
        granted = tenant.site
        granted.name = "Granted Plaza"
        granted.save()
        other_customer = CustomerAccountFactory(
            organization=tenant.organization, name="Hidden Customer Ltd"
        )
        SiteFactory(customer=other_customer, name="Hidden Annex")
        MembershipSiteGrantFactory(membership=tenant.membership, site=granted)

        client.force_login(tenant.user)
        body = client.get(reverse("app:organization")).content.decode()
        assert "Granted Plaza" in body
        assert "Hidden Annex" not in body
        assert "Hidden Customer Ltd" not in body

    def test_tenant_wide_role_still_sees_every_site(self, client) -> None:  # type: ignore[no-untyped-def]
        """Positive control: the narrowing applies to supervisors, not to everyone."""
        tenant = make_tenant("owner-sees-all", roles=(Role.OWNER,))
        other_customer = CustomerAccountFactory(
            organization=tenant.organization, name="Second Customer Ltd"
        )
        SiteFactory(customer=other_customer, name="Second Site")
        client.force_login(tenant.user)
        body = client.get(reverse("app:organization")).content.decode()
        assert tenant.site.name in body
        assert "Second Site" in body
        assert "Second Customer Ltd" in body

    def test_supervisor_with_a_second_tenant_wide_role_is_not_narrowed(self, client) -> None:  # type: ignore[no-untyped-def]
        """Union semantics: supervisor + operations manager is tenant-wide."""
        tenant = make_tenant("supervisor-plus", roles=(Role.SUPERVISOR, Role.OPERATIONS_MANAGER))
        other_customer = CustomerAccountFactory(
            organization=tenant.organization, name="Visible Customer Ltd"
        )
        SiteFactory(customer=other_customer, name="Visible Annex")
        assert tenant.membership.site_grants.count() == 0
        client.force_login(tenant.user)
        body = client.get(reverse("app:organization")).content.decode()
        assert "Visible Annex" in body
