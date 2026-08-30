"""Read paths for ingestion. Every function takes an explicit organization."""

from __future__ import annotations

import datetime as dt
import uuid

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.ingestion.models import (
    FINANCIAL_FIELD_GROUPS,
    DataSource,
    IdentityResolutionIssue,
    ImportBatch,
    ReconciliationIssue,
)
from apps.organizations.models import Membership
from apps.organizations.policy import effective_site_scope


def batches_for_organization(organization_id: uuid.UUID) -> QuerySet[ImportBatch]:
    return ImportBatch.objects.filter(organization_id=organization_id).select_related(
        "source", "uploaded_by"
    )


def get_batch_or_none(organization_id: uuid.UUID, batch_id: uuid.UUID) -> ImportBatch | None:
    return batches_for_organization(organization_id).filter(id=batch_id).first()


def sources_for_organization(organization_id: uuid.UUID) -> QuerySet[DataSource]:
    return DataSource.objects.filter(organization_id=organization_id).order_by("system_key")


def open_identity_issues(organization_id: uuid.UUID) -> QuerySet[IdentityResolutionIssue]:
    return IdentityResolutionIssue.objects.filter(
        organization_id=organization_id, status=IdentityResolutionIssue.Status.UNRESOLVED
    ).select_related("supplied_source")


def open_reconciliation_issues(
    organization_id: uuid.UUID,
    *,
    limit_to_site_ids: set[uuid.UUID] | None = None,
    include_financial: bool = True,
) -> QuerySet[ReconciliationIssue]:
    """Open reconciliation issues visible to a reader with this scope.

    Unlike an identity issue -- which by definition names a reference that has NOT
    resolved to a canonical entity, and therefore has no site to be scoped to -- a
    reconciliation issue names exactly one typed canonical subject, enforced by
    `ck_reconciliation_issue_one_subject`. Two of those seven subjects resolve
    **unambiguously** to a single site:

    * ``site``       -- the subject is the site itself;
    * ``work_order`` -- a work order belongs to exactly one site.

    The other five (customer, contract, service obligation, accounting invoice,
    accounting payment) are customer-wide, multi-site, or financial. They cannot be
    attributed to one granted site, so a site-scoped reader does not see them at all.
    Guessing which site a customer-wide conflict "really" belongs to is exactly the kind
    of inference this product refuses to make elsewhere.

    `limit_to_site_ids` follows the three-valued contract: `None` is tenant-wide, a set
    is those sites, and the **empty set is no sites** -- it reaches `__in=[]` verbatim
    and yields nothing.

    `include_financial=False` additionally hides contract/rate and invoice-status
    conflicts, which belong to the finance reviewer regardless of site.
    """
    queryset = ReconciliationIssue.objects.filter(
        organization_id=organization_id, status=ReconciliationIssue.Status.OPEN
    ).select_related("chosen_source")

    if not include_financial:
        queryset = queryset.exclude(field_group__in=FINANCIAL_FIELD_GROUPS)

    if limit_to_site_ids is not None:
        queryset = queryset.filter(
            Q(site_id__in=limit_to_site_ids) | Q(work_order__site_id__in=limit_to_site_ids)
        )
    return queryset


def open_reconciliation_issues_for(membership: Membership) -> QuerySet[ReconciliationIssue]:
    """The reconciliation issues this membership may read. One door, so surfaces agree.

    Every reconciliation surface -- the queue, the badge count on the imports page, and
    anything added later -- must call this rather than assembling the scope itself. The
    count and the list drifting apart is how a reader learns that something exists which
    they cannot see, and it is the same shape as the cockpit defect Phase 2 closed.

    Section 9.3 read model, unchanged by this correction: owner, operations manager,
    finance reviewer and auditor read tenant-wide. A supervisor reads only non-financial
    issues that resolve to a site they were explicitly granted.
    """
    scope = effective_site_scope(membership)
    return open_reconciliation_issues(
        membership.organization_id,
        limit_to_site_ids=scope,
        # Tenant-wide readers keep the finance conflicts; a site-scoped reader never does.
        include_financial=scope is None,
    )


def source_freshness(organization_id: uuid.UUID, *, now: dt.datetime | None = None) -> list[dict]:
    """Freshness per source, honestly labelled.

    Section 12, principle 12: "A daily CSV cannot drive a credible minute-by-minute
    alert." A source with no `maximum_age_minutes` is reported `unknown` rather than
    assumed fresh.
    """
    moment = now or timezone.now()
    rows = []
    for source in sources_for_organization(organization_id):
        observed = source.last_source_as_of_at
        if observed is None:
            status, age_minutes = "unknown", None
        else:
            age_minutes = int((moment - observed).total_seconds() // 60)
            if source.maximum_age_minutes is None:
                status = "unknown"
            elif age_minutes > source.maximum_age_minutes:
                status = "stale"
            elif age_minutes > source.maximum_age_minutes * 0.75:
                status = "aging"
            else:
                status = "fresh"
        rows.append(
            {
                "source": source,
                "status": status,
                "age_minutes": age_minutes,
                "maximum_age_minutes": source.maximum_age_minutes,
            }
        )
    return rows
