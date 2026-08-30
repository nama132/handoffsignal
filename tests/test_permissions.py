"""Role matrix enforcement (master prompt section 9.3, tested per section 33.3).

Every test here pairs a denial with a positive control. A denial test that would also
pass against a policy that denies everything proves nothing.
"""

from __future__ import annotations

import pytest

from apps.organizations.models import MembershipRoleGrant, Organization
from apps.organizations.policy import (
    REASON_MEMBERSHIP_INACTIVE,
    REASON_NO_MEMBERSHIP,
    REASON_ORGANIZATION_NOT_ACTIVE,
    REASON_ROLE_NOT_PERMITTED,
    REASON_SITE_NOT_GRANTED,
    REASON_SITE_REQUIRED,
    REASON_UNKNOWN_ACTION,
    Denied,
    allows,
    check,
    require,
)
from apps.organizations.roles import (
    ACTION_ROLES,
    PHASE_2_ENFORCEABLE,
    SITE_SCOPED_ACTIONS,
    STATE_CHANGING_ACTIONS,
    Action,
    Role,
)
from tests.factories import (
    MembershipFactory,
    MembershipSiteGrantFactory,
    OrganizationFactory,
    SiteFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

ALL_ROLES = [
    Role.OWNER,
    Role.OPERATIONS_MANAGER,
    Role.SUPERVISOR,
    Role.FINANCE_REVIEWER,
    Role.AUDITOR,
]


def membership_with(*roles):  # type: ignore[no-untyped-def]
    return MembershipFactory(roles=list(roles))


class TestFullRoleMatrix:
    """Every (role, action) pair must match the section 9.3 table exactly."""

    @pytest.mark.parametrize("role", ALL_ROLES)
    @pytest.mark.parametrize("action", sorted(ACTION_ROLES))
    def test_matrix_pair(self, role: str, action: str) -> None:
        membership = membership_with(role)
        site = SiteFactory(customer__organization=membership.organization)
        if role == Role.SUPERVISOR and action in SITE_SCOPED_ACTIONS:
            MembershipSiteGrantFactory(membership=membership, site=site)

        expected = role in ACTION_ROLES[action]
        decision = check(membership, action, site_id=site.id)
        assert bool(decision) is expected, (
            f"{role} on {action}: expected {expected}, got {decision.allowed} "
            f"({decision.reason_code})"
        )

    def test_matrix_is_not_all_true(self) -> None:
        """Guard against a policy that accidentally permits everything."""
        auditor = membership_with(Role.AUDITOR)
        denied = [a for a in ACTION_ROLES if not allows(auditor, a)]
        assert len(denied) == len(STATE_CHANGING_ACTIONS)

    def test_matrix_is_not_all_false(self) -> None:
        """Guard against a policy that accidentally denies everything."""
        owner = membership_with(Role.OWNER)
        permitted = [a for a in ACTION_ROLES if allows(owner, a)]
        assert len(permitted) >= len(PHASE_2_ENFORCEABLE)


class TestAuditorIsReadOnly:
    @pytest.mark.parametrize("action", sorted(STATE_CHANGING_ACTIONS))
    def test_auditor_cannot_perform_any_state_changing_action(self, action: str) -> None:
        auditor = membership_with(Role.AUDITOR)
        assert not allows(auditor, action)

    def test_auditor_can_view(self) -> None:
        assert allows(membership_with(Role.AUDITOR), Action.VIEW_ORGANIZATION)


class TestBoundaryRules:
    def test_finance_reviewer_cannot_approve_an_operational_handoff(self) -> None:
        finance = membership_with(Role.FINANCE_REVIEWER)
        assert not allows(finance, Action.APPROVE_OPERATIONAL_HANDOFF)
        # positive control: they can approve invoice-ready
        assert allows(finance, Action.APPROVE_INVOICE_READY)

    def test_operations_manager_cannot_approve_invoice_ready(self) -> None:
        ops = membership_with(Role.OPERATIONS_MANAGER)
        assert not allows(ops, Action.APPROVE_INVOICE_READY)
        assert allows(ops, Action.APPROVE_OPERATIONAL_HANDOFF)

    def test_operations_manager_cannot_commit_a_financial_import(self) -> None:
        ops = membership_with(Role.OPERATIONS_MANAGER)
        assert not allows(ops, Action.COMMIT_FINANCIAL_IMPORT)
        assert allows(ops, Action.COMMIT_OPERATIONAL_IMPORT)

    def test_finance_reviewer_cannot_commit_an_operational_import(self) -> None:
        finance = membership_with(Role.FINANCE_REVIEWER)
        assert not allows(finance, Action.COMMIT_OPERATIONAL_IMPORT)
        assert allows(finance, Action.COMMIT_FINANCIAL_IMPORT)

    @pytest.mark.parametrize(
        "role", [Role.OPERATIONS_MANAGER, Role.SUPERVISOR, Role.FINANCE_REVIEWER, Role.AUDITOR]
    )
    def test_identity_decisions_require_the_owner(self, role: str) -> None:
        """Line 372: an identity decision crossing the operational/financial boundary
        requires the owner. Visibility never implies this authority."""
        assert not allows(membership_with(role), Action.RESOLVE_IDENTITY)
        assert not allows(membership_with(role), Action.COMMIT_CROSSWALK_IMPORT)

    def test_owner_may_resolve_identity(self) -> None:
        assert allows(membership_with(Role.OWNER), Action.RESOLVE_IDENTITY)


class TestSupervisorSiteScope:
    def test_supervisor_with_zero_grants_reaches_no_site(self) -> None:
        supervisor = membership_with(Role.SUPERVISOR)
        site = SiteFactory(customer__organization=supervisor.organization)
        decision = check(supervisor, Action.ACT_ON_CASE, site_id=site.id)
        assert not decision
        assert decision.reason_code == REASON_SITE_NOT_GRANTED

    def test_supervisor_with_a_grant_reaches_that_site(self) -> None:
        supervisor = membership_with(Role.SUPERVISOR)
        site = SiteFactory(customer__organization=supervisor.organization)
        MembershipSiteGrantFactory(membership=supervisor, site=site)
        assert allows(supervisor, Action.ACT_ON_CASE, site_id=site.id)

    def test_a_grant_to_one_site_does_not_expose_another(self) -> None:
        supervisor = membership_with(Role.SUPERVISOR)
        granted = SiteFactory(customer__organization=supervisor.organization)
        other = SiteFactory(customer__organization=supervisor.organization)
        MembershipSiteGrantFactory(membership=supervisor, site=granted)
        assert allows(supervisor, Action.ACT_ON_CASE, site_id=granted.id)
        assert not allows(supervisor, Action.ACT_ON_CASE, site_id=other.id)

    def test_site_scoped_action_without_a_site_is_denied_for_supervisor(self) -> None:
        supervisor = membership_with(Role.SUPERVISOR)
        decision = check(supervisor, Action.ACT_ON_CASE, site_id=None)
        assert not decision
        assert decision.reason_code == REASON_SITE_REQUIRED

    def test_tenant_wide_role_is_not_narrowed_by_site_grants(self) -> None:
        ops = membership_with(Role.OPERATIONS_MANAGER)
        site = SiteFactory(customer__organization=ops.organization)
        assert ops.site_grants.count() == 0
        assert allows(ops, Action.ACT_ON_CASE, site_id=site.id)

    def test_supervisor_plus_tenant_wide_role_is_not_site_limited(self) -> None:
        """Union semantics: a second tenant-wide grant lifts the site restriction."""
        membership = membership_with(Role.SUPERVISOR, Role.OPERATIONS_MANAGER)
        site = SiteFactory(customer__organization=membership.organization)
        assert membership.site_grants.count() == 0
        assert allows(membership, Action.ACT_ON_CASE, site_id=site.id)


class TestMembershipAndOrganizationState:
    def test_no_membership_is_denied(self) -> None:
        decision = check(None, Action.VIEW_ORGANIZATION)
        assert not decision
        assert decision.reason_code == REASON_NO_MEMBERSHIP

    def test_inactive_membership_loses_access(self) -> None:
        membership = membership_with(Role.OWNER)
        assert allows(membership, Action.VIEW_ORGANIZATION)
        membership.is_active = False
        membership.save()
        decision = check(membership, Action.VIEW_ORGANIZATION)
        assert not decision
        assert decision.reason_code == REASON_MEMBERSHIP_INACTIVE

    @pytest.mark.parametrize(
        "status", [Organization.Status.SUSPENDED, Organization.Status.ARCHIVED]
    )
    def test_non_active_organization_permits_nothing(self, status: str) -> None:
        membership = membership_with(Role.OWNER)
        membership.organization.status = status
        membership.organization.save()
        membership.refresh_from_db()
        decision = check(membership, Action.VIEW_ORGANIZATION)
        assert not decision
        assert decision.reason_code == REASON_ORGANIZATION_NOT_ACTIVE

    def test_membership_with_no_role_grant_is_denied(self) -> None:
        membership = MembershipFactory()
        assert membership.active_roles == set()
        decision = check(membership, Action.VIEW_ORGANIZATION)
        assert not decision
        assert decision.reason_code == REASON_ROLE_NOT_PERMITTED

    def test_revoked_grant_no_longer_permits(self) -> None:
        from django.utils import timezone

        membership = membership_with(Role.OWNER)
        assert allows(membership, Action.MANAGE_MEMBERSHIPS)
        grant = membership.role_grants.get()
        grant.revoked_at = timezone.now()
        grant.save()
        membership.refresh_from_db()
        assert not allows(membership, Action.MANAGE_MEMBERSHIPS)

    def test_regrant_after_revocation_restores_access(self) -> None:
        from django.utils import timezone

        membership = membership_with(Role.OWNER)
        grant = membership.role_grants.get()
        grant.revoked_at = timezone.now()
        grant.save()
        MembershipRoleGrant.objects.create(membership=membership, role=Role.OWNER)
        membership.refresh_from_db()
        assert allows(membership, Action.MANAGE_MEMBERSHIPS)


class TestUnknownActionAndRaising:
    def test_unknown_action_is_denied(self) -> None:
        decision = check(membership_with(Role.OWNER), "not_a_real_action")
        assert not decision
        assert decision.reason_code == REASON_UNKNOWN_ACTION

    def test_require_raises_for_a_denied_action(self) -> None:
        with pytest.raises(Denied):
            require(membership_with(Role.AUDITOR), Action.MANAGE_MEMBERSHIPS)

    def test_require_returns_a_decision_when_permitted(self) -> None:
        decision = require(membership_with(Role.OWNER), Action.MANAGE_MEMBERSHIPS)
        assert decision.allowed
        assert Role.OWNER in decision.granting_roles


class TestPlatformStaffSeparation:
    def test_django_is_staff_grants_no_tenant_authority(self) -> None:
        """Tenant owner and Django is_staff are different things (line 835)."""
        staff_user = UserFactory(email="platform@example.test", is_staff=True)
        organization = OrganizationFactory()
        membership = MembershipFactory(organization=organization, user=staff_user)
        assert staff_user.is_staff is True
        assert not allows(membership, Action.MANAGE_MEMBERSHIPS)
        assert not allows(membership, Action.VIEW_ORGANIZATION)

    def test_tenant_owner_is_not_platform_staff(self) -> None:
        membership = membership_with(Role.OWNER)
        assert membership.user.is_staff is False
        assert allows(membership, Action.MANAGE_MEMBERSHIPS)
