"""Test factories.

Everything here is synthetic. Factories deliberately do NOT set an organization by
default on child objects: each factory takes its parent explicitly so a test cannot
accidentally create a cross-tenant graph and then "prove" isolation against data that
was never separated.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import factory
from django.utils import timezone

from apps.ingestion.models import DataSource, ExternalEntityReference
from apps.operations.models import (
    AccountingInvoice,
    AccountingPayment,
    Contract,
    ContractSite,
    CustomerAccount,
    ServiceObligation,
    Site,
    WorkOrder,
)
from apps.organizations.models import (
    Membership,
    MembershipRoleGrant,
    MembershipSiteGrant,
    Organization,
    User,
)
from apps.organizations.roles import Role


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("email",)

    email = factory.Sequence(lambda n: f"user{n}@example.test")
    display_name = factory.Sequence(lambda n: f"User {n}")
    is_active = True


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization
        django_get_or_create = ("slug",)

    slug = factory.Sequence(lambda n: f"org-{n}")
    display_name = factory.Sequence(lambda n: f"Organization {n}")
    default_timezone = "America/New_York"
    status = Organization.Status.ACTIVE


class MembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Membership
        # The post_generation hook saves its own rows; factory_boy's extra save is
        # extraneous and deprecated.
        skip_postgeneration_save = True

    organization = factory.SubFactory(OrganizationFactory)
    user = factory.SubFactory(UserFactory)
    is_active = True

    @factory.post_generation
    def roles(self, create, extracted, **kwargs):  # type: ignore[no-untyped-def]
        """Usage: MembershipFactory(roles=[Role.OWNER])."""
        if not create or not extracted:
            return
        for role in extracted:
            MembershipRoleGrant.objects.create(membership=self, role=role)


class MembershipSiteGrantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MembershipSiteGrant

    membership = factory.SubFactory(MembershipFactory)


class CustomerAccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CustomerAccount

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"Customer {n}")


class SiteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Site

    organization = factory.SelfAttribute("customer.organization")
    customer = factory.SubFactory(CustomerAccountFactory)
    name = factory.Sequence(lambda n: f"Site {n}")
    timezone = "America/New_York"
    region_code = "NOVA-CENTRAL"
    site_type = Site.SiteType.OFFICE


class ContractFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Contract

    organization = factory.SelfAttribute("customer.organization")
    customer = factory.SubFactory(CustomerAccountFactory)
    starts_on = dt.date(2026, 1, 1)
    currency = "USD"
    contract_reference = factory.Sequence(lambda n: f"CT-{n:04d}")


class ContractSiteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ContractSite

    organization = factory.SelfAttribute("contract.organization")
    contract = factory.SubFactory(ContractFactory)
    # The site MUST hang off the same customer as the contract, otherwise each
    # SubFactory would mint its own customer — and therefore its own organization —
    # producing a cross-tenant graph that quietly invalidates any test built on it.
    site = factory.SubFactory(SiteFactory, customer=factory.SelfAttribute("..contract.customer"))
    effective_from = dt.date(2026, 1, 1)


class ServiceObligationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ServiceObligation

    organization = factory.SelfAttribute("contract_site.organization")
    contract_site = factory.SubFactory(ContractSiteFactory)
    code = factory.Sequence(lambda n: f"OB-{n:04d}")
    label = "Nightly janitorial"
    service_type = "janitorial_nightly"
    scope_kind = ServiceObligation.ScopeKind.BASE_RECURRING
    service_window_start = dt.time(18, 0)
    service_window_end = dt.time(2, 0)
    service_weekdays = "mon,tue,wed,thu,fri"
    role_code = "cleaner"
    required_coverage_count = 2
    substitution_required_when_below_count = True
    billing_basis = ServiceObligation.BillingBasis.FIXED_WORK_ORDER
    extra_work_requires_authorization = True
    uninvoiced_delay_days = 7
    effective_from = dt.date(2026, 1, 1)


class WorkOrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WorkOrder

    organization = factory.SelfAttribute("site.organization")
    customer = factory.SelfAttribute("site.customer")
    site = factory.SubFactory(SiteFactory)
    contract = factory.SubFactory(
        ContractFactory, customer=factory.SelfAttribute("..site.customer")
    )
    title = "Post-construction detail clean"
    status = WorkOrder.Status.COMPLETED
    completed_at = factory.LazyFunction(timezone.now)
    billable = True
    authorization_required = False
    billing_basis = ServiceObligation.BillingBasis.FIXED_WORK_ORDER
    approved_fixed_amount = Decimal("480.0000")
    source_as_of_at = factory.LazyFunction(timezone.now)


class DataSourceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DataSource

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"Source {n}")
    system_key = factory.Sequence(lambda n: f"source-{n}")
    domain = DataSource.Domain.SERVICE_EVENTS
    is_authoritative = True


class ExternalEntityReferenceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ExternalEntityReference

    organization = factory.SelfAttribute("source.organization")
    source = factory.SubFactory(DataSourceFactory)
    entity_type = ExternalEntityReference.EntityType.CUSTOMER
    external_id = factory.Sequence(lambda n: f"EXT-{n:05d}")
    mapping_status = ExternalEntityReference.MappingStatus.UNRESOLVED


class AccountingInvoiceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccountingInvoice

    organization = factory.SelfAttribute("site.organization")
    customer = factory.SelfAttribute("site.customer")
    site = factory.SubFactory(SiteFactory)
    service_date = dt.date(2026, 6, 1)
    invoice_reference = factory.Sequence(lambda n: f"INV-{n:05d}")
    invoice_amount = Decimal("480.0000")
    invoiced_at = factory.LazyFunction(timezone.now)
    currency = "USD"
    source_status = AccountingInvoice.SourceStatus.POSTED
    source_as_of_at = factory.LazyFunction(timezone.now)


class AccountingPaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccountingPayment

    organization = factory.SelfAttribute("accounting_invoice.organization")
    accounting_invoice = factory.SubFactory(AccountingInvoiceFactory)
    payment_reference = factory.Sequence(lambda n: f"PMT-{n:05d}")
    collected_amount = Decimal("480.0000")
    collected_at = factory.LazyFunction(timezone.now)
    currency = "USD"
    source_status = AccountingPayment.SourceStatus.POSTED
    source_as_of_at = factory.LazyFunction(timezone.now)


def make_tenant(slug: str, *, roles=(Role.OWNER,)):  # type: ignore[no-untyped-def]
    """Build a complete, self-consistent tenant graph.

    Returns a simple namespace with organization, user, membership, customer, site,
    contract, contract_site, obligation, and work_order — all in the same organization.
    """
    from types import SimpleNamespace

    organization = OrganizationFactory(slug=slug, display_name=slug.title())
    user = UserFactory(email=f"{slug}-user@example.test")
    membership = MembershipFactory(organization=organization, user=user, roles=list(roles))
    customer = CustomerAccountFactory(organization=organization, name=f"{slug} Customer")
    site = SiteFactory(customer=customer, name=f"{slug} Site")
    contract = ContractFactory(customer=customer)
    contract_site = ContractSiteFactory(contract=contract, site=site)
    obligation = ServiceObligationFactory(contract_site=contract_site)
    work_order = WorkOrderFactory(site=site, contract=contract, service_obligation=obligation)
    return SimpleNamespace(
        organization=organization,
        user=user,
        membership=membership,
        customer=customer,
        site=site,
        contract=contract,
        contract_site=contract_site,
        obligation=obligation,
        work_order=work_order,
    )
