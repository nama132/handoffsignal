"""Read paths for ingestion. Every function takes an explicit organization."""

from __future__ import annotations

import datetime as dt
import uuid

from django.db.models import QuerySet
from django.utils import timezone

from apps.ingestion.models import (
    DataSource,
    IdentityResolutionIssue,
    ImportBatch,
    ReconciliationIssue,
)


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


def open_reconciliation_issues(organization_id: uuid.UUID) -> QuerySet[ReconciliationIssue]:
    return ReconciliationIssue.objects.filter(
        organization_id=organization_id, status=ReconciliationIssue.Status.OPEN
    ).select_related("chosen_source")


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
