"""Shared fixtures for Phase 4 tests: a fully loaded, ready Atlas run."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings

from apps.ingestion.models import DataSource, IdentityResolutionIssue
from apps.ingestion.services import coverage as coverage_service
from apps.ingestion.services import identity, reconciliation
from apps.ingestion.services import imports as import_service
from apps.operations.models import Site, WorkOrder
from apps.organizations.models import Organization, User

FIXTURES = Path(settings.BASE_DIR) / "sample_data" / "atlas_facility_services"
AS_OF = dt.datetime(2026, 8, 20, 10, 0, tzinfo=dt.UTC)

PLAN = [
    ("sites_contracts.csv", "sites_contracts", "contract_register", "contract_scope", ""),
    ("entity_crosswalk.csv", "entity_crosswalk", "opsplatform_idmap", "entity_crosswalk", ""),
    (
        "work_orders_service_events.csv",
        "work_orders_service_events",
        "opsplatform_workorders",
        "work_order",
        "SERVICE_EVENT_CURRENT_STATE_V1",
    ),
    (
        "invoice_status.csv",
        "invoice_status",
        "ar_ledger",
        "accounting_invoice",
        "ACCOUNTING_SERVICE_DATE_LEDGER_V1",
    ),
]


def declaration(
    family, query_contract="", completeness="complete", scope_type="organization", **scope
):  # type: ignore[no-untyped-def]
    return coverage_service.CoverageDeclaration(
        record_family=family,
        scope_type=scope_type,
        coverage_start_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        coverage_end_at=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
        query_contract_code=query_contract,
        query_contract_version=1,
        completeness=completeness,
        declaration_basis="synthetic_fixture",
        **scope,
    )


def seed_atlas():  # type: ignore[no-untyped-def]
    from django.core.management import call_command

    call_command("seed_demo", verbosity=0)
    return Organization.objects.get(slug="atlas-facility-services"), User.objects.get(
        email="owner@atlas.example"
    )


def load_atlas(
    organization,
    actor,
    *,
    run_key="test-run",
    invoice_payload=None,
    invoice_completeness="complete",
    invoice_mode="full_snapshot",
    resolve_identity=True,
):  # type: ignore[no-untyped-def]
    """Load all four files, attach to a run, optionally resolve the deliberate quarantine."""
    run = reconciliation.open_run(organization=organization, run_key=run_key, as_of=AS_OF)
    for filename, kind, source_key, family, query_contract in PLAN:
        source = DataSource.objects.get(organization=organization, system_key=source_key)
        payload = (FIXTURES / filename).read_bytes()
        mode, completeness = "full_snapshot", "complete"
        if kind == "invoice_status":
            payload = invoice_payload if invoice_payload is not None else payload
            mode, completeness = invoice_mode, invoice_completeness
        result = import_service.upload(
            organization=organization,
            source=source,
            kind=kind,
            filename=filename,
            payload=payload,
            observation_mode=mode,
            source_as_of_at=AS_OF,
            declarations=[declaration(family, query_contract, completeness)],
            actor=actor,
        )
        batch = import_service.commit(result.batch, actor)
        reconciliation.attach_batch(run, batch)

    if resolve_identity:
        for issue in IdentityResolutionIssue.objects.filter(
            organization=organization, status="unresolved"
        ):
            identity.resolve_issue_manually(
                issue=issue,
                target=Site.objects.get(
                    organization=organization, name="Potomac Distribution Annex"
                ),
                resolved_by=actor,
            )
    run = reconciliation.evaluate_readiness(run)
    return SimpleNamespace(run=run, organization=organization, actor=actor)


def star_work_order(organization):  # type: ignore[no-untyped-def]
    return WorkOrder.objects.get(organization=organization, title__startswith="Post-construction")


def invoice_csv_without_star_row() -> bytes:
    """The stock invoice file: it deliberately contains NO invoice for the star case."""
    return (FIXTURES / "invoice_status.csv").read_bytes()


def invoice_csv_header_only() -> bytes:
    """An EMPTY accounting export: header row only."""
    text = (FIXTURES / "invoice_status.csv").read_text()
    return (text.splitlines()[0] + "\n").encode()


def invoice_csv_with_star_invoice(*, status="posted") -> bytes:
    """Adds a posted (or void) invoice matching the star case by customer/site/service date."""
    text = (FIXTURES / "invoice_status.csv").read_text()
    row = (
        "ar_ledger,80000999-1753900000,,,ar_ledger,80000042-1739216455,ar_ledger,80000107-1739216455,"
        f"2026-07-06,3450,480.00,2026-07-20T09:00:00-04:00,{status},,,,,,USD,,2026-08-20T06:00:00-04:00\n"
    )
    return (text.rstrip("\n") + "\n" + row).encode()
