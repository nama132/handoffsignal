"""Model invariants for the Phase 2 domain.

Constraints that the specification states explicitly are asserted against the database
where possible, not merely against Python validation, because a service can be bypassed
and a database constraint cannot.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.ingestion.models import (
    DataSource,
    ExternalEntityReference,
    IdentityResolutionIssue,
    ReconciliationIssue,
    SourcePrecedenceEntry,
    SourcePrecedenceRule,
)
from apps.operations.models import (
    AccountingPayment,
    ContractSite,
    ServiceObligation,
    Site,
    WorkOrder,
)
from apps.organizations.models import Membership, MembershipRoleGrant, Organization
from apps.organizations.roles import Role
from tests.factories import (
    AccountingInvoiceFactory,
    AccountingPaymentFactory,
    ContractFactory,
    ContractSiteFactory,
    CustomerAccountFactory,
    DataSourceFactory,
    MembershipFactory,
    MembershipSiteGrantFactory,
    OrganizationFactory,
    ServiceObligationFactory,
    SiteFactory,
    UserFactory,
    WorkOrderFactory,
    make_tenant,
)

pytestmark = pytest.mark.django_db


class TestOrganizationAndMembership:
    def test_slug_is_globally_unique(self) -> None:
        OrganizationFactory(slug="dup-slug")
        with pytest.raises(IntegrityError):
            Organization.objects.create(slug="dup-slug", display_name="Other")

    def test_invalid_timezone_is_rejected(self) -> None:
        org = OrganizationFactory.build(
            slug="tz", display_name="TZ", default_timezone="Mars/Olympus"
        )
        with pytest.raises(ValidationError):
            org.full_clean()

    def test_valid_timezone_is_accepted(self) -> None:
        OrganizationFactory.build(
            slug="tz2", display_name="TZ", default_timezone="America/Chicago"
        ).full_clean()

    def test_one_membership_per_user_and_organization(self) -> None:
        membership = MembershipFactory()
        with pytest.raises(IntegrityError):
            Membership.objects.create(organization=membership.organization, user=membership.user)

    def test_same_user_may_belong_to_two_organizations(self) -> None:
        user = UserFactory()
        MembershipFactory(user=user, organization=OrganizationFactory(slug="o1"))
        MembershipFactory(user=user, organization=OrganizationFactory(slug="o2"))
        assert Membership.objects.filter(user=user).count() == 2

    def test_only_one_active_grant_per_role(self) -> None:
        membership = MembershipFactory(roles=[Role.OWNER])
        with pytest.raises(IntegrityError):
            MembershipRoleGrant.objects.create(membership=membership, role=Role.OWNER)

    def test_a_revoked_grant_allows_a_new_active_grant(self) -> None:
        """The unique index is partial, so history can accumulate."""
        membership = MembershipFactory(roles=[Role.OWNER])
        grant = membership.role_grants.get()
        grant.revoked_at = timezone.now()
        grant.save()
        MembershipRoleGrant.objects.create(membership=membership, role=Role.OWNER)
        assert membership.role_grants.count() == 2

    def test_multiple_distinct_roles_are_permitted(self) -> None:
        membership = MembershipFactory(roles=[Role.OPERATIONS_MANAGER, Role.FINANCE_REVIEWER])
        assert membership.active_roles == {Role.OPERATIONS_MANAGER, Role.FINANCE_REVIEWER}

    def test_site_grant_is_unique_per_membership_and_site(self) -> None:
        tenant = make_tenant("grant-dupe")
        MembershipSiteGrantFactory(membership=tenant.membership, site=tenant.site)
        with pytest.raises(IntegrityError):
            MembershipSiteGrantFactory(membership=tenant.membership, site=tenant.site)

    def test_there_is_no_wildcard_site_grant_field(self) -> None:
        """A wildcard would make deny-by-default unprovable (line 841)."""
        from apps.organizations.models import MembershipSiteGrant

        field_names = {f.name for f in MembershipSiteGrant._meta.get_fields()}
        for forbidden in ("all_sites", "is_wildcard", "grants_all", "site_wildcard"):
            assert forbidden not in field_names


class TestSiteAndTimezone:
    def test_site_requires_a_valid_iana_timezone(self) -> None:
        customer = CustomerAccountFactory()
        site = Site(
            organization=customer.organization,
            customer=customer,
            name="Bad TZ",
            timezone="Not/AZone",
        )
        with pytest.raises(ValidationError):
            site.full_clean()

    def test_sites_may_hold_different_timezones_in_one_organization(self) -> None:
        customer = CustomerAccountFactory()
        SiteFactory(customer=customer, name="East", timezone="America/New_York")
        SiteFactory(customer=customer, name="West", timezone="America/Los_Angeles")

    def test_site_does_not_store_an_address_field(self) -> None:
        """Section 22.4 forbids addresses, alarm codes, and access instructions."""
        field_names = {f.name for f in Site._meta.get_fields()}
        for forbidden in (
            "address",
            "street",
            "postcode",
            "zip_code",
            "alarm_code",
            "access_code",
            "key_location",
        ):
            assert forbidden not in field_names


class TestServiceObligationWindows:
    def test_overnight_window_is_allowed_and_detected(self) -> None:
        """A window ending before it starts crosses midnight; this is legitimate."""
        obligation = ServiceObligationFactory(
            service_window_start=dt.time(18, 0), service_window_end=dt.time(2, 0)
        )
        assert obligation.crosses_midnight is True

    def test_same_day_window_is_not_flagged_as_overnight(self) -> None:
        obligation = ServiceObligationFactory(
            service_window_start=dt.time(9, 0), service_window_end=dt.time(17, 0)
        )
        assert obligation.crosses_midnight is False

    def test_coverage_count_must_be_positive(self) -> None:
        with pytest.raises(IntegrityError):
            ServiceObligationFactory(required_coverage_count=0)

    def test_uninvoiced_delay_is_bounded(self) -> None:
        with pytest.raises(IntegrityError):
            ServiceObligationFactory(uninvoiced_delay_days=400)

    def test_hourly_basis_requires_a_rate(self) -> None:
        obligation = ServiceObligationFactory.build(
            contract_site=ContractSiteFactory(),
            billing_basis=ServiceObligation.BillingBasis.HOURLY_ACTUAL,
            default_bill_rate=None,
        )
        obligation.organization = obligation.contract_site.organization
        with pytest.raises(ValidationError):
            obligation.full_clean()

    def test_unique_per_site_code_and_effective_date(self) -> None:
        obligation = ServiceObligationFactory()
        with pytest.raises(IntegrityError):
            ServiceObligationFactory(
                contract_site=obligation.contract_site,
                code=obligation.code,
                effective_from=obligation.effective_from,
            )

    def test_same_code_may_be_reissued_on_a_later_effective_date(self) -> None:
        obligation = ServiceObligationFactory()
        ServiceObligationFactory(
            contract_site=obligation.contract_site,
            code=obligation.code,
            effective_from=obligation.effective_from + dt.timedelta(days=365),
        )


class TestEffectivePeriods:
    def test_contract_site_period_must_be_ordered(self) -> None:
        contract = ContractFactory()
        site = SiteFactory(customer=contract.customer)
        with pytest.raises(IntegrityError):
            ContractSite.objects.create(
                organization=contract.organization,
                contract=contract,
                site=site,
                effective_from=dt.date(2026, 6, 1),
                effective_to=dt.date(2026, 1, 1),
            )

    def test_overlapping_contract_site_periods_are_rejected(self) -> None:
        first = ContractSiteFactory(
            effective_from=dt.date(2026, 1, 1), effective_to=dt.date(2026, 12, 31)
        )
        overlapping = ContractSite(
            organization=first.organization,
            contract=first.contract,
            site=first.site,
            effective_from=dt.date(2026, 6, 1),
        )
        with pytest.raises(ValidationError):
            overlapping.full_clean()

    def test_adjacent_half_open_periods_do_not_overlap(self) -> None:
        """[a, b) followed by [b, c) is legal: the boundary belongs to the later row."""
        first = ContractSiteFactory(
            effective_from=dt.date(2026, 1, 1), effective_to=dt.date(2026, 7, 1)
        )
        adjacent = ContractSite(
            organization=first.organization,
            contract=first.contract,
            site=first.site,
            effective_from=dt.date(2026, 7, 1),
        )
        adjacent.full_clean()

    def test_contract_active_on_respects_dates_and_status(self) -> None:
        contract = ContractFactory(starts_on=dt.date(2026, 1, 1), ends_on=dt.date(2026, 12, 31))
        assert contract.is_active_on(dt.date(2026, 6, 1)) is True
        assert contract.is_active_on(dt.date(2025, 12, 31)) is False
        assert contract.is_active_on(dt.date(2027, 1, 1)) is False
        contract.status = contract.Status.ENDED
        assert contract.is_active_on(dt.date(2026, 6, 1)) is False

    def test_contract_end_before_start_is_rejected(self) -> None:
        customer = CustomerAccountFactory()
        with pytest.raises(IntegrityError):
            ContractFactory(
                customer=customer, starts_on=dt.date(2026, 6, 1), ends_on=dt.date(2026, 1, 1)
            )


class TestMoneySemantics:
    def test_amounts_are_decimal_not_float(self) -> None:
        work_order = WorkOrderFactory(approved_fixed_amount=Decimal("480.00"))
        work_order.refresh_from_db()
        assert isinstance(work_order.approved_fixed_amount, Decimal)

    def test_decimal_precision_is_preserved(self) -> None:
        work_order = WorkOrderFactory(bill_rate=Decimal("37.5525"))
        work_order.refresh_from_db()
        assert work_order.bill_rate == Decimal("37.5525")

    def test_unknown_amount_is_null_not_zero(self) -> None:
        """Section 22.5: "Unknown is NULL, not zero."."""
        work_order = WorkOrderFactory(approved_fixed_amount=None)
        work_order.refresh_from_db()
        assert work_order.approved_fixed_amount is None
        assert work_order.approved_fixed_amount != Decimal("0")

    def test_true_zero_is_distinguishable_from_unknown(self) -> None:
        work_order = WorkOrderFactory(approved_fixed_amount=Decimal("0"))
        work_order.refresh_from_db()
        assert work_order.approved_fixed_amount == Decimal("0")
        assert work_order.approved_fixed_amount is not None

    def test_negative_amounts_are_rejected(self) -> None:
        with pytest.raises(IntegrityError):
            WorkOrderFactory(approved_fixed_amount=Decimal("-1.00"))

    def test_negative_invoice_amount_is_rejected(self) -> None:
        with pytest.raises(IntegrityError):
            AccountingInvoiceFactory(invoice_amount=Decimal("-5.00"))

    def test_payment_currency_must_match_the_invoice(self) -> None:
        invoice = AccountingInvoiceFactory(currency="USD")
        payment = AccountingPayment(
            organization=invoice.organization,
            accounting_invoice=invoice,
            payment_reference="P-1",
            collected_amount=Decimal("10.00"),
            collected_at=timezone.now(),
            currency="EUR",
            source_status=AccountingPayment.SourceStatus.POSTED,
            source_as_of_at=timezone.now(),
        )
        with pytest.raises(ValidationError):
            payment.full_clean()

    def test_one_invoice_may_have_several_payments(self) -> None:
        invoice = AccountingInvoiceFactory()
        AccountingPaymentFactory(accounting_invoice=invoice, collected_amount=Decimal("100"))
        AccountingPaymentFactory(accounting_invoice=invoice, collected_amount=Decimal("380"))
        assert invoice.payments.count() == 2

    def test_only_posted_invoices_count_toward_actuals(self) -> None:
        posted = AccountingInvoiceFactory(source_status="posted")
        void = AccountingInvoiceFactory(source_status="void")
        assert posted.counts_toward_actuals is True
        assert void.counts_toward_actuals is False


class TestWorkOrderInvariants:
    def test_completed_work_order_must_have_a_timestamp(self) -> None:
        with pytest.raises(IntegrityError):
            WorkOrderFactory(status=WorkOrder.Status.COMPLETED, completed_at=None)

    def test_open_work_order_needs_no_timestamp(self) -> None:
        WorkOrderFactory(status=WorkOrder.Status.OPEN, completed_at=None)

    def test_authorization_is_satisfied_only_with_reference_and_date(self) -> None:
        work_order = WorkOrderFactory(authorization_required=True)
        assert work_order.has_required_authorization is False
        work_order.authorization_reference = "AUTH-1"
        assert work_order.has_required_authorization is False
        work_order.authorized_at = timezone.now()
        assert work_order.has_required_authorization is True

    def test_authorization_not_required_is_always_satisfied(self) -> None:
        assert WorkOrderFactory(authorization_required=False).has_required_authorization is True


class TestExternalEntityReferenceConstraints:
    """Section 22.3's conditional typed-target rules, enforced in the database."""

    def _confirmed(self, **kwargs):  # type: ignore[no-untyped-def]
        tenant = make_tenant(kwargs.pop("slug", "ext-ref"))
        source = DataSourceFactory(organization=tenant.organization)
        defaults = {
            "organization": tenant.organization,
            "source": source,
            "entity_type": ExternalEntityReference.EntityType.CUSTOMER,
            "external_id": "C-1",
            "mapping_status": ExternalEntityReference.MappingStatus.CONFIRMED,
            "match_method": ExternalEntityReference.MatchMethod.MANUAL,
            "confirmed_at": timezone.now(),
            "customer": tenant.customer,
        }
        defaults.update(kwargs)
        return ExternalEntityReference(**defaults), tenant

    def test_confirmed_requires_exactly_one_target(self) -> None:
        reference, _ = self._confirmed()
        reference.full_clean()
        reference.save()

    def test_confirmed_with_no_target_is_rejected_by_the_database(self) -> None:
        reference, _ = self._confirmed(customer=None)
        with pytest.raises(IntegrityError), transaction.atomic():
            reference.save()

    def test_confirmed_with_two_targets_is_rejected_by_the_database(self) -> None:
        reference, tenant = self._confirmed()
        reference.site = tenant.site
        with pytest.raises(IntegrityError), transaction.atomic():
            reference.save()

    def test_unresolved_with_a_target_is_rejected_by_the_database(self) -> None:
        reference, tenant = self._confirmed(
            mapping_status=ExternalEntityReference.MappingStatus.UNRESOLVED,
            match_method="",
            confirmed_at=None,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            reference.save()

    def test_unresolved_with_no_target_is_accepted(self) -> None:
        reference, _ = self._confirmed(
            mapping_status=ExternalEntityReference.MappingStatus.UNRESOLVED,
            match_method="",
            confirmed_at=None,
            customer=None,
        )
        reference.save()

    def test_confirmed_without_provenance_is_rejected(self) -> None:
        reference, _ = self._confirmed(confirmed_at=None)
        with pytest.raises(IntegrityError), transaction.atomic():
            reference.save()

    def test_entity_type_must_match_the_populated_target(self) -> None:
        reference, tenant = self._confirmed(entity_type=ExternalEntityReference.EntityType.SITE)
        with pytest.raises(ValidationError):
            reference.full_clean()

    def test_only_one_current_reference_per_source_identity(self) -> None:
        reference, tenant = self._confirmed()
        reference.save()
        duplicate, _ = self._confirmed(slug="ext-ref-2")
        duplicate.organization = reference.organization
        duplicate.source = reference.source
        duplicate.customer = reference.customer
        duplicate.external_id = reference.external_id
        with pytest.raises(IntegrityError), transaction.atomic():
            duplicate.save()

    def test_a_superseded_reference_frees_the_identity(self) -> None:
        reference, _ = self._confirmed()
        reference.save()
        reference.mapping_status = ExternalEntityReference.MappingStatus.SUPERSEDED
        reference.save()
        replacement = ExternalEntityReference(
            organization=reference.organization,
            source=reference.source,
            entity_type=reference.entity_type,
            external_id=reference.external_id,
            mapping_status=ExternalEntityReference.MappingStatus.CONFIRMED,
            match_method=ExternalEntityReference.MatchMethod.MANUAL,
            confirmed_at=timezone.now(),
            customer=reference.customer,
            supersedes=reference,
        )
        replacement.save()
        assert reference.is_current is False
        assert replacement.is_current is True

    def test_no_match_method_permits_fuzzy_auto_confirmation(self) -> None:
        """Line 938: fuzzy/AI matching may never auto-confirm."""
        values = set(ExternalEntityReference.MatchMethod.values)
        assert values == {"partner_canonical_key", "manual", "deterministic_exact"}
        for forbidden in ("fuzzy", "ai", "probabilistic", "similarity", "auto"):
            assert not any(forbidden in v for v in values)


class TestIdentityAndReconciliationIssues:
    def test_unresolved_issue_blocks_dependents(self) -> None:
        tenant = make_tenant("id-issue")
        issue = IdentityResolutionIssue.objects.create(
            organization=tenant.organization,
            supplied_source=DataSourceFactory(organization=tenant.organization),
            entity_type=ExternalEntityReference.EntityType.WORK_ORDER,
            supplied_external_id="00518774",
            reason_code=IdentityResolutionIssue.Reason.UNRESOLVED_IDENTITY,
        )
        assert issue.blocks_dependents is True

    def test_resolution_must_be_attributed(self) -> None:
        tenant = make_tenant("id-issue-2")
        with pytest.raises(IntegrityError):
            IdentityResolutionIssue.objects.create(
                organization=tenant.organization,
                supplied_source=DataSourceFactory(organization=tenant.organization),
                entity_type=ExternalEntityReference.EntityType.WORK_ORDER,
                supplied_external_id="X",
                reason_code=IdentityResolutionIssue.Reason.AMBIGUOUS_IDENTITY,
                status=IdentityResolutionIssue.Status.RESOLVED,
            )

    def test_only_one_open_issue_per_supplied_identity(self) -> None:
        tenant = make_tenant("id-issue-3")
        source = DataSourceFactory(organization=tenant.organization)
        common = {
            "organization": tenant.organization,
            "supplied_source": source,
            "entity_type": ExternalEntityReference.EntityType.WORK_ORDER,
            "supplied_external_id": "DUP",
            "reason_code": IdentityResolutionIssue.Reason.UNRESOLVED_IDENTITY,
        }
        IdentityResolutionIssue.objects.create(**common)
        with pytest.raises(IntegrityError):
            IdentityResolutionIssue.objects.create(**common)

    def test_reconciliation_issue_needs_exactly_one_subject(self) -> None:
        tenant = make_tenant("recon")
        with pytest.raises(IntegrityError), transaction.atomic():
            ReconciliationIssue.objects.create(
                organization=tenant.organization,
                field_group=SourcePrecedenceRule.FieldGroup.CONTRACT_RATE,
                entity_type=ExternalEntityReference.EntityType.WORK_ORDER,
                explanation="two sources disagree",
            )

    def test_open_blocking_issue_blocks_dependents(self) -> None:
        tenant = make_tenant("recon-2")
        issue = ReconciliationIssue.objects.create(
            organization=tenant.organization,
            field_group=SourcePrecedenceRule.FieldGroup.CONTRACT_RATE,
            entity_type=ExternalEntityReference.EntityType.WORK_ORDER,
            explanation="rate mismatch",
            work_order=tenant.work_order,
        )
        assert issue.blocks_dependents is True
        issue.is_blocking = False
        assert issue.blocks_dependents is False


class TestSourcePrecedence:
    def test_precedence_entries_are_ordered_and_unique(self) -> None:
        tenant = make_tenant("prec")
        rule = SourcePrecedenceRule.objects.create(
            organization=tenant.organization,
            entity_type=ExternalEntityReference.EntityType.WORK_ORDER,
            field_group=SourcePrecedenceRule.FieldGroup.CONTRACT_RATE,
            conflict_policy=SourcePrecedenceRule.ConflictPolicy.BLOCK_AND_REVIEW,
            effective_from=dt.date(2026, 1, 1),
        )
        first = DataSourceFactory(organization=tenant.organization, system_key="contract_register")
        second = DataSourceFactory(organization=tenant.organization, system_key="opsplatform")
        SourcePrecedenceEntry.objects.create(
            organization=tenant.organization, rule=rule, source=first, rank=1
        )
        SourcePrecedenceEntry.objects.create(
            organization=tenant.organization, rule=rule, source=second, rank=2
        )
        assert [e.source.system_key for e in rule.entries.all()] == [
            "contract_register",
            "opsplatform",
        ]

    def test_two_sources_cannot_share_a_rank(self) -> None:
        tenant = make_tenant("prec-2")
        rule = SourcePrecedenceRule.objects.create(
            organization=tenant.organization,
            entity_type=ExternalEntityReference.EntityType.WORK_ORDER,
            field_group=SourcePrecedenceRule.FieldGroup.CONTRACT_RATE,
            conflict_policy=SourcePrecedenceRule.ConflictPolicy.PREFER_AUTHORITATIVE,
            effective_from=dt.date(2026, 1, 1),
        )
        SourcePrecedenceEntry.objects.create(
            organization=tenant.organization,
            rule=rule,
            source=DataSourceFactory(organization=tenant.organization, system_key="a"),
            rank=1,
        )
        with pytest.raises(IntegrityError):
            SourcePrecedenceEntry.objects.create(
                organization=tenant.organization,
                rule=rule,
                source=DataSourceFactory(organization=tenant.organization, system_key="b"),
                rank=1,
            )

    def test_conflict_policy_has_no_implicit_last_write_wins(self) -> None:
        """Line 959: never use whichever file imported last as hidden precedence."""
        values = set(SourcePrecedenceRule.ConflictPolicy.values)
        assert "latest_import" not in values
        assert "last_write_wins" not in values
        assert values == {
            "block_and_review",
            "prefer_authoritative",
            "latest_within_authoritative_source",
        }

    def test_source_domain_vocabulary_matches_the_seven_import_contracts(self) -> None:
        assert set(DataSource.Domain.values) == {
            "contracts",
            "identity_crosswalk",
            "workers",
            "schedule",
            "time",
            "service_events",
            "invoice_status",
        }


class TestFactoriesProduceSameTenantGraphs:
    """Meta-tests.

    A factory that silently mints a second organization for a child object would make
    every isolation test built on it meaningless — the objects were never in the same
    tenant to begin with. These assert the fixtures themselves are coherent.
    """

    def test_contract_site_factory_is_single_tenant(self) -> None:
        link = ContractSiteFactory()
        assert link.contract.organization_id == link.site.organization_id
        assert link.organization_id == link.contract.organization_id
        link.full_clean()

    def test_service_obligation_factory_is_single_tenant(self) -> None:
        obligation = ServiceObligationFactory()
        assert obligation.organization_id == obligation.contract_site.organization_id
        obligation.full_clean()

    def test_work_order_factory_is_single_tenant(self) -> None:
        work_order = WorkOrderFactory()
        assert work_order.organization_id == work_order.site.organization_id
        assert work_order.organization_id == work_order.contract.organization_id
        assert work_order.organization_id == work_order.customer.organization_id
        work_order.full_clean()

    def test_accounting_invoice_factory_is_single_tenant(self) -> None:
        invoice = AccountingInvoiceFactory()
        assert invoice.organization_id == invoice.site.organization_id
        assert invoice.organization_id == invoice.customer.organization_id
        invoice.full_clean()

    def test_make_tenant_builds_one_coherent_organization(self) -> None:
        tenant = make_tenant("coherence-check")
        organization_ids = {
            tenant.customer.organization_id,
            tenant.site.organization_id,
            tenant.contract.organization_id,
            tenant.contract_site.organization_id,
            tenant.obligation.organization_id,
            tenant.work_order.organization_id,
            tenant.membership.organization_id,
        }
        assert organization_ids == {tenant.organization.id}
