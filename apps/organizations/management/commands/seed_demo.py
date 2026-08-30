"""Seed the synthetic demo organizations.

Section 31. Route B scope: this seeds tenancy, roles, and the Journey B operational
domain only. It deliberately does NOT seed the ~12 workers, shifts, badge/training
expiry, the Spanish-preferring worker, the failed inspection, or the no-check-in
exception described in section 31 — those belong to Journeys A and C, which are
unbuilt (Phase 0A matrix, line 2296).

A second organization, Beacon Building Care, exists solely so tenant-isolation tests
have a real neighbour to be denied against (section 31, line 2016).

All data is fictional. Region codes are coarse; no addresses, alarm codes, or keys are
stored anywhere.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.ingestion.models import DataSource
from apps.operations.models import (
    Contract,
    ContractSite,
    CustomerAccount,
    ServiceObligation,
    Site,
)
from apps.organizations.management.commands._guards import refuse_outside_local_or_demo
from apps.organizations.models import (
    Membership,
    MembershipRoleGrant,
    MembershipSiteGrant,
    Organization,
    User,
)
from apps.organizations.roles import Role

DEMO_PASSWORD = "demo-only-not-a-real-password"  # noqa: S105 - local synthetic accounts

ATLAS_USERS = [
    ("owner@atlas.example", "Alex Owner", [Role.OWNER]),
    ("ops@atlas.example", "Ops Manager", [Role.OPERATIONS_MANAGER]),
    ("supervisor@atlas.example", "Site Supervisor", [Role.SUPERVISOR]),
    ("finance@atlas.example", "Finance Reviewer", [Role.FINANCE_REVIEWER]),
    ("auditor@atlas.example", "Read Only Auditor", [Role.AUDITOR]),
]

# customer name, site name, site_type, region_code, uninvoiced delay days
ATLAS_SITES = [
    (
        "Meridian Property Group",
        "Meridian Business Center",
        Site.SiteType.OFFICE,
        "NOVA-CENTRAL",
        7,
    ),
    ("Capital Retail Partners", "Capital Retail Gallery", Site.SiteType.RETAIL, "DC-CORE", 10),
    (
        "Potomac Logistics LLC",
        "Potomac Distribution Annex",
        Site.SiteType.LIGHT_INDUSTRIAL,
        "MD-MONTGOMERY",
        5,
    ),
]

# Four sources with deliberately distinct namespaces. Two are the same fictional vendor
# emitting different feeds, which is exactly the case section 22.3 warns must not share
# a system_key.
ATLAS_SOURCES = [
    (
        "contract_register",
        "Contract & Scope Register Export",
        DataSource.Domain.CONTRACTS,
        True,
        10080,
        43200,
    ),
    (
        "opsplatform_workorders",
        "Ops Platform — Work Order Export",
        DataSource.Domain.SERVICE_EVENTS,
        True,
        1440,
        2880,
    ),
    (
        "opsplatform_idmap",
        "Ops Platform — Integration ID Map",
        DataSource.Domain.IDENTITY_CROSSWALK,
        True,
        10080,
        None,
    ),
    (
        "ar_ledger",
        "Accounting AR Ledger Export",
        DataSource.Domain.INVOICE_STATUS,
        True,
        1440,
        2880,
    ),
]


class Command(BaseCommand):
    help = "Create or refresh the synthetic demo organizations (local/demo only)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing synthetic demo data before seeding.",
        )

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        refuse_outside_local_or_demo("seed_demo")

        if options["reset"]:
            self._reset()

        atlas = self._seed_atlas()
        beacon = self._seed_isolation_neighbour()

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {atlas.slug} ({atlas.memberships.count()} memberships, "
                f"{atlas.operations_site_set.count()} sites) and "
                f"{beacon.slug} ({beacon.operations_site_set.count()} sites)."
            )
        )
        self.stdout.write(
            "Route B: no workers, shifts, time entries, or quality events are seeded."
        )

    def _reset(self) -> None:
        """Remove synthetic data through a guarded V2-only path.

        Deletion runs in dependency order because almost every foreign key is PROTECT:
        a stale order fails loudly rather than orphaning rows. The list is derived from
        the apps in reverse build order (recovery -> exceptions -> ingestion ->
        operations -> organizations), which is the order the models depend on.
        """
        from apps.audit.models import AuditEvent
        from apps.exceptions.models import (
            DetectorDispatchIntent,
            DetectorRun,
            DetectorScheduleLease,
            ExceptionCase,
            ExceptionEvent,
            ExceptionSourceLink,
            FinancialImpactSnapshot,
            FinancialRecoveryItem,
        )
        from apps.ingestion.models import (
            ExternalEntityReference,
            IdentityResolutionIssue,
            ImportBatch,
            ImportCoverage,
            ImportRow,
            ReconciliationIssue,
            ReconciliationRun,
            ReconciliationRunInput,
            SourcePrecedenceEntry,
            SourcePrecedenceRule,
            SourceRecordVersion,
        )
        from apps.operations.models import AccountingInvoice, AccountingPayment, WorkOrder
        from apps.recovery.models import Approval, FinanceExport, FinancialStageEvent

        slugs = ["atlas-facility-services", "beacon-building-care"]
        organizations = Organization.objects.filter(slug__in=slugs)
        if not organizations.exists():
            return

        scoped = {"organization__in": organizations}

        # Append-only models refuse delete() on the instance; the queryset path is the
        # deliberate administrative escape hatch, and it is reachable only from this
        # local/demo-guarded command.
        FinanceExport.objects.filter(**scoped).update(superseded_note="")
        for export in FinanceExport.objects.filter(**scoped):
            export.items.clear()
        FinanceExport.objects.filter(**scoped)._raw_delete(FinanceExport.objects.db)
        Approval.objects.filter(**scoped).delete()
        FinancialStageEvent.objects.filter(**scoped).delete()

        FinancialRecoveryItem.objects.filter(**scoped).delete()
        FinancialImpactSnapshot.objects.filter(**scoped).delete()
        ExceptionSourceLink.objects.filter(**scoped).delete()
        ExceptionEvent.objects.filter(**scoped).delete()
        ExceptionCase.objects.filter(**scoped).delete()
        DetectorRun.objects.filter(**scoped).delete()
        DetectorDispatchIntent.objects.filter(**scoped).delete()
        DetectorScheduleLease.objects.filter(**scoped).delete()
        AuditEvent.objects.filter(**scoped).delete()

        ReconciliationRunInput.objects.filter(**scoped).delete()
        ReconciliationRun.objects.filter(**scoped).delete()
        IdentityResolutionIssue.objects.filter(**scoped).delete()
        ReconciliationIssue.objects.filter(**scoped).delete()
        ExternalEntityReference.objects.filter(**scoped).delete()
        SourcePrecedenceEntry.objects.filter(**scoped).delete()
        SourcePrecedenceRule.objects.filter(**scoped).delete()
        ImportRow.objects.filter(**scoped).delete()
        ImportCoverage.objects.filter(**scoped).delete()
        SourceRecordVersion.objects.filter(**scoped).delete()
        ImportBatch.objects.filter(**scoped).delete()

        AccountingPayment.objects.filter(**scoped).delete()
        AccountingInvoice.objects.filter(**scoped).delete()
        WorkOrder.objects.filter(**scoped).delete()
        ServiceObligation.objects.filter(**scoped).delete()
        ContractSite.objects.filter(**scoped).delete()
        Contract.objects.filter(**scoped).delete()
        Site.objects.filter(**scoped).delete()
        CustomerAccount.objects.filter(**scoped).delete()
        DataSource.objects.filter(**scoped).delete()

        MembershipSiteGrant.objects.filter(membership__organization__in=organizations).delete()
        MembershipRoleGrant.objects.filter(membership__organization__in=organizations).delete()
        Membership.objects.filter(**scoped).delete()
        organizations.delete()
        self.stdout.write("Existing synthetic demo data removed.")

    def _seed_atlas(self) -> Organization:
        organization, _ = Organization.objects.get_or_create(
            slug="atlas-facility-services",
            defaults={
                "display_name": "Atlas Facility Services",
                "default_timezone": "America/New_York",
                "demo_mode": True,
            },
        )

        for email, display_name, roles in ATLAS_USERS:
            user, created = User.objects.get_or_create(
                email=email, defaults={"display_name": display_name}
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])
            membership, _ = Membership.objects.get_or_create(
                organization=organization, user=user, defaults={"is_active": True}
            )
            for role in roles:
                MembershipRoleGrant.objects.get_or_create(
                    membership=membership, role=role, revoked_at=None
                )

        for key, name, domain, authoritative, cadence, max_age in ATLAS_SOURCES:
            DataSource.objects.get_or_create(
                organization=organization,
                system_key=key,
                defaults={
                    "name": name,
                    "domain": domain,
                    "is_authoritative": authoritative,
                    "expected_cadence_minutes": cadence,
                    "maximum_age_minutes": max_age,
                },
            )

        starts_on = dt.date(2026, 1, 1)
        for index, (customer_name, site_name, site_type, region, delay) in enumerate(ATLAS_SITES):
            customer, _ = CustomerAccount.objects.get_or_create(
                organization=organization, name=customer_name
            )
            site, _ = Site.objects.get_or_create(
                organization=organization,
                name=site_name,
                defaults={
                    "customer": customer,
                    "timezone": "America/New_York",
                    "region_code": region,
                    "site_type": site_type,
                },
            )
            contract, _ = Contract.objects.get_or_create(
                organization=organization,
                customer=customer,
                contract_reference=f"CT-2026-{customer_name.split()[0].upper()}-01",
                defaults={"starts_on": starts_on, "currency": "USD"},
            )
            contract_site, _ = ContractSite.objects.get_or_create(
                organization=organization,
                contract=contract,
                site=site,
                effective_from=starts_on,
            )
            ServiceObligation.objects.get_or_create(
                organization=organization,
                contract_site=contract_site,
                code=f"OB-{index + 1:02d}-BASE",
                effective_from=starts_on,
                defaults={
                    "label": f"{site_name} nightly janitorial",
                    "service_type": "janitorial_nightly",
                    "scope_kind": ServiceObligation.ScopeKind.BASE_RECURRING,
                    # Crosses midnight deliberately: exercises overnight window handling.
                    "service_window_start": dt.time(18, 0),
                    "service_window_end": dt.time(2, 0),
                    "service_weekdays": "mon,tue,wed,thu,fri",
                    "role_code": "cleaner",
                    "required_coverage_count": 2,
                    "substitution_required_when_below_count": True,
                    "billing_basis": ServiceObligation.BillingBasis.INCLUDED,
                    "extra_work_requires_authorization": True,
                    "uninvoiced_delay_days": delay,
                },
            )
        return organization

    def _seed_isolation_neighbour(self) -> Organization:
        """A second tenant, used only to prove isolation."""
        organization, _ = Organization.objects.get_or_create(
            slug="beacon-building-care",
            defaults={
                "display_name": "Beacon Building Care",
                "default_timezone": "America/Chicago",
                "demo_mode": True,
            },
        )
        user, created = User.objects.get_or_create(
            email="owner@beacon.example", defaults={"display_name": "Blake Owner"}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])
        membership, _ = Membership.objects.get_or_create(
            organization=organization, user=user, defaults={"is_active": True}
        )
        MembershipRoleGrant.objects.get_or_create(
            membership=membership, role=Role.OWNER, revoked_at=None
        )
        customer, _ = CustomerAccount.objects.get_or_create(
            organization=organization, name="Lakeside Offices LLC"
        )
        Site.objects.get_or_create(
            organization=organization,
            name="Lakeside Tower",
            defaults={
                "customer": customer,
                "timezone": "America/Chicago",
                "region_code": "IL-CENTRAL",
                "site_type": Site.SiteType.OFFICE,
            },
        )
        return organization
