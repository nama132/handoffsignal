"""Two-tenant isolation (master prompt section 33.3).

"For two organizations A and B, prove: A cannot list, view, mutate, transition,
export, download, prepare a handoff, or audit B's objects even when B's UUID is known."

Every isolation test knows B's real UUID. A test that used a random UUID would pass
against a system with no isolation at all.
"""

from __future__ import annotations

import uuid

import pytest
from django.core.exceptions import ValidationError

from apps.ingestion.models import ExternalEntityReference
from apps.operations.selectors import (
    accounting_invoices_for_organization,
    contracts_for_organization,
    customers_for_organization,
    get_site_or_none,
    obligations_for_organization,
    sites_for_organization,
    work_orders_for_organization,
)
from apps.organizations.roles import Role
from apps.organizations.selectors import active_memberships_for, membership_for
from tests.factories import (
    ContractFactory,
    ContractSiteFactory,
    CustomerAccountFactory,
    DataSourceFactory,
    ExternalEntityReferenceFactory,
    MembershipSiteGrantFactory,
    SiteFactory,
    make_tenant,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenants():  # type: ignore[no-untyped-def]
    """Two fully-populated, entirely separate tenants."""
    from types import SimpleNamespace

    return SimpleNamespace(
        a=make_tenant("alpha-cleaning", roles=(Role.OWNER,)),
        b=make_tenant("beta-facilities", roles=(Role.OWNER,)),
    )


class TestSelectorIsolation:
    """Selectors scoped to A must never return B's rows, even though both exist."""

    def test_customers(self, tenants) -> None:  # type: ignore[no-untyped-def]
        result = list(customers_for_organization(tenants.a.organization.id))
        assert tenants.a.customer in result
        assert tenants.b.customer not in result

    def test_sites(self, tenants) -> None:  # type: ignore[no-untyped-def]
        result = list(sites_for_organization(tenants.a.organization.id))
        assert tenants.a.site in result
        assert tenants.b.site not in result

    def test_contracts(self, tenants) -> None:  # type: ignore[no-untyped-def]
        result = list(contracts_for_organization(tenants.a.organization.id))
        assert tenants.a.contract in result
        assert tenants.b.contract not in result

    def test_obligations(self, tenants) -> None:  # type: ignore[no-untyped-def]
        result = list(obligations_for_organization(tenants.a.organization.id))
        assert tenants.a.obligation in result
        assert tenants.b.obligation not in result

    def test_work_orders(self, tenants) -> None:  # type: ignore[no-untyped-def]
        result = list(work_orders_for_organization(tenants.a.organization.id))
        assert tenants.a.work_order in result
        assert tenants.b.work_order not in result

    def test_accounting_invoices(self, tenants) -> None:  # type: ignore[no-untyped-def]
        from tests.factories import AccountingInvoiceFactory

        invoice_a = AccountingInvoiceFactory(site=tenants.a.site)
        invoice_b = AccountingInvoiceFactory(site=tenants.b.site)
        result = list(accounting_invoices_for_organization(tenants.a.organization.id))
        assert invoice_a in result
        assert invoice_b not in result

    def test_detail_lookup_with_a_known_foreign_uuid_returns_none(self, tenants) -> None:  # type: ignore[no-untyped-def]
        """The caller holds B's real site UUID and still gets nothing."""
        known_uuid = tenants.b.site.id
        assert get_site_or_none(tenants.a.organization.id, known_uuid) is None
        # Positive control: the same call inside B does find it.
        assert get_site_or_none(tenants.b.organization.id, known_uuid) == tenants.b.site


class TestMembershipIsolation:
    def test_membership_lookup_across_tenants_returns_none(self, tenants) -> None:  # type: ignore[no-untyped-def]
        assert membership_for(tenants.a.user, tenants.b.organization.id) is None
        assert membership_for(tenants.a.user, tenants.a.organization.id) is not None

    def test_active_memberships_lists_only_own(self, tenants) -> None:  # type: ignore[no-untyped-def]
        orgs = {m.organization_id for m in active_memberships_for(tenants.a.user)}
        assert orgs == {tenants.a.organization.id}

    def test_inactive_membership_is_not_selectable(self, tenants) -> None:  # type: ignore[no-untyped-def]
        tenants.a.membership.is_active = False
        tenants.a.membership.save()
        assert list(active_memberships_for(tenants.a.user)) == []

    def test_membership_of_suspended_organization_is_not_selectable(self, tenants) -> None:  # type: ignore[no-untyped-def]
        tenants.a.organization.status = "suspended"
        tenants.a.organization.save()
        assert list(active_memberships_for(tenants.a.user)) == []


class TestCrossTenantForeignKeyRejection:
    """Section 22.1: every tenant-owned foreign key must stay inside one organization."""

    def test_site_cannot_reference_another_tenants_customer(self, tenants) -> None:  # type: ignore[no-untyped-def]
        site = SiteFactory.build(
            organization=tenants.a.organization,
            customer=tenants.b.customer,
            timezone="America/New_York",
        )
        with pytest.raises(ValidationError):
            site.full_clean()

    def test_contract_cannot_reference_another_tenants_customer(self, tenants) -> None:  # type: ignore[no-untyped-def]
        contract = ContractFactory.build(
            organization=tenants.a.organization, customer=tenants.b.customer
        )
        with pytest.raises(ValidationError):
            contract.full_clean()

    def test_contract_site_cannot_join_across_tenants(self, tenants) -> None:  # type: ignore[no-untyped-def]
        link = ContractSiteFactory.build(
            organization=tenants.a.organization,
            contract=tenants.a.contract,
            site=tenants.b.site,
        )
        with pytest.raises(ValidationError):
            link.full_clean()

    def test_work_order_cannot_reference_another_tenants_site(self, tenants) -> None:  # type: ignore[no-untyped-def]
        from tests.factories import WorkOrderFactory

        work_order = WorkOrderFactory.build(
            organization=tenants.a.organization,
            customer=tenants.a.customer,
            site=tenants.b.site,
            contract=tenants.a.contract,
        )
        with pytest.raises(ValidationError):
            work_order.full_clean()

    def test_site_grant_cannot_cross_tenants(self, tenants) -> None:  # type: ignore[no-untyped-def]
        grant = MembershipSiteGrantFactory.build(
            membership=tenants.a.membership, site=tenants.b.site
        )
        with pytest.raises(ValidationError):
            grant.full_clean()

    def test_external_reference_cannot_target_another_tenants_entity(self, tenants) -> None:  # type: ignore[no-untyped-def]
        source = DataSourceFactory(organization=tenants.a.organization)
        reference = ExternalEntityReference(
            organization=tenants.a.organization,
            source=source,
            entity_type=ExternalEntityReference.EntityType.CUSTOMER,
            external_id="X-1",
            mapping_status=ExternalEntityReference.MappingStatus.CONFIRMED,
            match_method=ExternalEntityReference.MatchMethod.MANUAL,
            customer=tenants.b.customer,
        )
        with pytest.raises(ValidationError):
            reference.full_clean()

    def test_same_tenant_assignment_is_accepted(self, tenants) -> None:  # type: ignore[no-untyped-def]
        """Positive control: the guard rejects cross-tenant, not everything."""
        site = SiteFactory.build(
            organization=tenants.a.organization,
            customer=tenants.a.customer,
            name="Valid Same-Tenant Site",
            timezone="America/New_York",
        )
        site.full_clean()


class TestOrganizationScopedUniqueness:
    """Section 17, rule 3: names and source ids are never globally unique."""

    def test_two_tenants_may_share_a_customer_name(self, tenants) -> None:  # type: ignore[no-untyped-def]
        CustomerAccountFactory(organization=tenants.a.organization, name="Shared Name Ltd")
        CustomerAccountFactory(organization=tenants.b.organization, name="Shared Name Ltd")

    def test_one_tenant_cannot_duplicate_a_customer_name(self, tenants) -> None:  # type: ignore[no-untyped-def]
        from django.db import IntegrityError

        CustomerAccountFactory(organization=tenants.a.organization, name="Unique Ltd")
        with pytest.raises(IntegrityError):
            CustomerAccountFactory(organization=tenants.a.organization, name="Unique Ltd")

    def test_two_tenants_may_share_a_site_name(self, tenants) -> None:  # type: ignore[no-untyped-def]
        SiteFactory(customer=tenants.a.customer, name="Main Building")
        SiteFactory(customer=tenants.b.customer, name="Main Building")

    def test_two_tenants_may_share_a_source_system_key(self, tenants) -> None:  # type: ignore[no-untyped-def]
        DataSourceFactory(organization=tenants.a.organization, system_key="ar_ledger")
        DataSourceFactory(organization=tenants.b.organization, system_key="ar_ledger")

    def test_one_tenant_cannot_duplicate_a_source_system_key(self, tenants) -> None:  # type: ignore[no-untyped-def]
        from django.db import IntegrityError

        DataSourceFactory(organization=tenants.a.organization, system_key="ar_ledger")
        with pytest.raises(IntegrityError):
            DataSourceFactory(organization=tenants.a.organization, system_key="ar_ledger")

    def test_two_tenants_may_share_an_external_id(self, tenants) -> None:  # type: ignore[no-untyped-def]
        source_a = DataSourceFactory(organization=tenants.a.organization, system_key="s")
        source_b = DataSourceFactory(organization=tenants.b.organization, system_key="s")
        ExternalEntityReferenceFactory(source=source_a, external_id="00084120")
        ExternalEntityReferenceFactory(source=source_b, external_id="00084120")


class TestSelectorsRequireExplicitOrganization:
    """Section 17, rule 5. A selector with a default organization would be a hole."""

    @pytest.mark.parametrize(
        "selector",
        [
            customers_for_organization,
            sites_for_organization,
            contracts_for_organization,
            obligations_for_organization,
            work_orders_for_organization,
            accounting_invoices_for_organization,
        ],
    )
    def test_selector_cannot_be_called_without_an_organization(self, selector) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(TypeError):
            selector()

    def test_empty_site_grant_set_returns_nothing_not_everything(self, tenants) -> None:  # type: ignore[no-untyped-def]
        """Deny by default: an empty grant set must never mean 'no filter'."""
        result = list(sites_for_organization(tenants.a.organization.id, limit_to_site_ids=set()))
        assert result == []
        # Positive control: None means unfiltered.
        assert list(sites_for_organization(tenants.a.organization.id)) != []

    def test_unknown_organization_returns_nothing(self) -> None:
        assert list(customers_for_organization(uuid.uuid4())) == []


class TestEveryTenantOwnedModelIsScoped:
    """Generic guard against the class of bug that hid in SourcePrecedenceEntry.

    A join table declared as a plain `models.Model` has no `organization` column, so
    nothing stops it joining two rows from different tenants. Rather than remembering
    to check each new model by hand, this introspects the apps and fails on any model
    that owns tenant data without a non-null organization foreign key.
    """

    #: Models that legitimately have no organization column.
    EXEMPT = {
        "User",  # platform identity; tenancy is expressed through Membership
        "Membership",  # has its own explicit organization FK
        "MembershipRoleGrant",  # reached only through Membership
        "MembershipSiteGrant",  # reached only through Membership
        "Organization",  # is the tenant
    }

    def test_all_tenant_models_carry_an_organization(self) -> None:
        from django.apps import apps

        offenders = []
        for label in ("organizations", "operations", "ingestion"):
            for model in apps.get_app_config(label).get_models():
                if model.__name__ in self.EXEMPT:
                    continue
                field_names = {f.name for f in model._meta.get_fields()}
                if "organization" not in field_names:
                    offenders.append(f"{label}.{model.__name__}")
                    continue
                field = model._meta.get_field("organization")
                assert not field.null, f"{model.__name__}.organization must be non-null"
        assert not offenders, (
            "These tenant-owned models have no organization column, so nothing prevents "
            f"a cross-tenant row: {sorted(offenders)}"
        )

    def test_the_guard_recognises_a_missing_organization(self) -> None:
        """Positive control: the check above is not vacuous."""
        from django.apps import apps

        user_fields = {f.name for f in apps.get_model("organizations", "User")._meta.get_fields()}
        assert "organization" not in user_fields


class TestSourcePrecedenceEntryIsolation:
    """Regression tests for the join-table cross-tenant hole."""

    def test_entry_is_tenant_scoped(self) -> None:
        from apps.ingestion.models import SourcePrecedenceEntry

        field_names = {f.name for f in SourcePrecedenceEntry._meta.get_fields()}
        assert "organization" in field_names

    def test_entry_cannot_join_a_rule_and_source_across_tenants(self, tenants) -> None:  # type: ignore[no-untyped-def]
        import datetime as dt

        from apps.ingestion.models import (
            ExternalEntityReference as Ref,
        )
        from apps.ingestion.models import (
            SourcePrecedenceEntry,
            SourcePrecedenceRule,
        )

        rule = SourcePrecedenceRule.objects.create(
            organization=tenants.a.organization,
            entity_type=Ref.EntityType.WORK_ORDER,
            field_group=SourcePrecedenceRule.FieldGroup.CONTRACT_RATE,
            conflict_policy=SourcePrecedenceRule.ConflictPolicy.BLOCK_AND_REVIEW,
            effective_from=dt.date(2026, 1, 1),
        )
        foreign_source = DataSourceFactory(organization=tenants.b.organization)
        entry = SourcePrecedenceEntry(
            organization=tenants.a.organization, rule=rule, source=foreign_source, rank=1
        )
        with pytest.raises(ValidationError):
            entry.full_clean()

    def test_same_tenant_entry_is_accepted(self, tenants) -> None:  # type: ignore[no-untyped-def]
        """Positive control."""
        import datetime as dt

        from apps.ingestion.models import (
            ExternalEntityReference as Ref,
        )
        from apps.ingestion.models import (
            SourcePrecedenceEntry,
            SourcePrecedenceRule,
        )

        rule = SourcePrecedenceRule.objects.create(
            organization=tenants.a.organization,
            entity_type=Ref.EntityType.WORK_ORDER,
            field_group=SourcePrecedenceRule.FieldGroup.CONTRACT_RATE,
            conflict_policy=SourcePrecedenceRule.ConflictPolicy.BLOCK_AND_REVIEW,
            effective_from=dt.date(2026, 1, 1),
        )
        own_source = DataSourceFactory(organization=tenants.a.organization)
        entry = SourcePrecedenceEntry(
            organization=tenants.a.organization, rule=rule, source=own_source, rank=1
        )
        entry.full_clean()
        entry.save()


class TestEffectiveSiteScope:
    """`effective_site_scope` is three-valued in effect; an empty set must never widen."""

    def test_tenant_wide_roles_return_none(self) -> None:
        from apps.organizations.policy import effective_site_scope

        for role in (Role.OWNER, Role.OPERATIONS_MANAGER, Role.FINANCE_REVIEWER, Role.AUDITOR):
            tenant = make_tenant(f"scope-{role}", roles=(role,))
            assert effective_site_scope(tenant.membership) is None

    def test_supervisor_with_no_grants_returns_an_empty_set_not_none(self) -> None:
        from apps.organizations.policy import effective_site_scope

        tenant = make_tenant("scope-supervisor-empty", roles=(Role.SUPERVISOR,))
        scope = effective_site_scope(tenant.membership)
        assert scope == set()
        assert scope is not None, "An empty set must never be collapsed to tenant-wide"

    def test_supervisor_with_grants_returns_exactly_those_sites(self) -> None:
        from apps.organizations.policy import effective_site_scope

        tenant = make_tenant("scope-supervisor-granted", roles=(Role.SUPERVISOR,))
        other = SiteFactory(customer=tenant.customer, name="Not Granted")
        MembershipSiteGrantFactory(membership=tenant.membership, site=tenant.site)
        scope = effective_site_scope(tenant.membership)
        assert scope == {tenant.site.id}
        assert other.id not in scope

    def test_supervisor_plus_tenant_wide_role_returns_none(self) -> None:
        from apps.organizations.policy import effective_site_scope

        tenant = make_tenant("scope-union", roles=(Role.SUPERVISOR, Role.FINANCE_REVIEWER))
        assert effective_site_scope(tenant.membership) is None

    def test_scoped_selectors_honour_an_empty_set(self, tenants) -> None:  # type: ignore[no-untyped-def]
        from apps.operations.selectors import (
            contracts_for_organization,
            customers_for_organization,
            obligations_for_organization,
            work_orders_for_organization,
        )

        org_id = tenants.a.organization.id
        for selector in (
            customers_for_organization,
            contracts_for_organization,
            obligations_for_organization,
            work_orders_for_organization,
        ):
            assert list(selector(org_id, limit_to_site_ids=set())) == [], selector.__name__
            assert list(selector(org_id)) != [], selector.__name__

    def test_get_site_or_none_respects_the_scope(self, tenants) -> None:  # type: ignore[no-untyped-def]
        assert get_site_or_none(tenants.a.organization.id, tenants.a.site.id) is not None
        assert (
            get_site_or_none(tenants.a.organization.id, tenants.a.site.id, limit_to_site_ids=set())
            is None
        )
