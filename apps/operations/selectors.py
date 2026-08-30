"""Read paths for the operational domain.

Section 17, rule 5: "Every selector requires an explicit organization argument."
Every function here takes `organization_id` as its first positional parameter and
filters on it. None of them accepts a default, so an unscoped call is a TypeError at
import-test time rather than a data leak at runtime.
"""

from __future__ import annotations

import uuid

from django.db.models import QuerySet

from apps.operations.models import (
    AccountingInvoice,
    Contract,
    CustomerAccount,
    ServiceObligation,
    Site,
    WorkOrder,
)


def customers_for_organization(
    organization_id: uuid.UUID, *, limit_to_site_ids: set[uuid.UUID] | None = None
) -> QuerySet[CustomerAccount]:
    """Customers in one organization, optionally narrowed to those owning a visible site.

    A supervisor scoped to one site must not learn the names of customers they cannot
    reach, so the narrowing is applied to customers as well as to sites.
    """
    queryset = CustomerAccount.objects.filter(organization_id=organization_id)
    if limit_to_site_ids is not None:
        queryset = queryset.filter(sites__id__in=limit_to_site_ids).distinct()
    return queryset.order_by("name")


def sites_for_organization(
    organization_id: uuid.UUID, *, limit_to_site_ids: set[uuid.UUID] | None = None
) -> QuerySet[Site]:
    """Sites in one organization.

    `limit_to_site_ids` narrows to a supervisor's explicit grants. Passing an empty set
    returns nothing, which is the correct deny-by-default behaviour — it must never be
    treated as "no filter" (section 22.2, line 841).
    """
    queryset = Site.objects.filter(organization_id=organization_id).select_related("customer")
    if limit_to_site_ids is not None:
        queryset = queryset.filter(id__in=limit_to_site_ids)
    return queryset.order_by("name")


def contracts_for_organization(
    organization_id: uuid.UUID, *, limit_to_site_ids: set[uuid.UUID] | None = None
) -> QuerySet[Contract]:
    queryset = Contract.objects.filter(organization_id=organization_id).select_related("customer")
    if limit_to_site_ids is not None:
        queryset = queryset.filter(contract_sites__site_id__in=limit_to_site_ids).distinct()
    return queryset


def obligations_for_organization(
    organization_id: uuid.UUID, *, limit_to_site_ids: set[uuid.UUID] | None = None
) -> QuerySet[ServiceObligation]:
    queryset = ServiceObligation.objects.filter(organization_id=organization_id).select_related(
        "contract_site", "contract_site__site"
    )
    if limit_to_site_ids is not None:
        queryset = queryset.filter(contract_site__site_id__in=limit_to_site_ids)
    return queryset


def work_orders_for_organization(
    organization_id: uuid.UUID, *, limit_to_site_ids: set[uuid.UUID] | None = None
) -> QuerySet[WorkOrder]:
    queryset = WorkOrder.objects.filter(organization_id=organization_id).select_related(
        "customer", "site", "contract"
    )
    if limit_to_site_ids is not None:
        queryset = queryset.filter(site_id__in=limit_to_site_ids)
    return queryset


def accounting_invoices_for_organization(
    organization_id: uuid.UUID, *, limit_to_site_ids: set[uuid.UUID] | None = None
) -> QuerySet[AccountingInvoice]:
    queryset = AccountingInvoice.objects.filter(organization_id=organization_id).select_related(
        "customer", "site"
    )
    if limit_to_site_ids is not None:
        queryset = queryset.filter(site_id__in=limit_to_site_ids)
    return queryset


def get_site_or_none(
    organization_id: uuid.UUID,
    site_id: uuid.UUID,
    *,
    limit_to_site_ids: set[uuid.UUID] | None = None,
) -> Site | None:
    """Fetch one site inside one organization.

    Returns None rather than raising so the caller can answer 404 for a cross-tenant id
    without revealing whether it exists elsewhere (section 17, rule 8).
    """
    if limit_to_site_ids is not None and site_id not in limit_to_site_ids:
        return None
    return Site.objects.filter(organization_id=organization_id, id=site_id).first()
