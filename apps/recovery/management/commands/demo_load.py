"""Load the complete Atlas demo story in one command.

Written for rehearsal: `make demo-reset` wipes the synthetic tenants, imports the four
CSVs in the correct order, resolves the deliberate identity quarantine, runs the
detector, and leaves one case ready to walk through.

It drives the same services the UI does — nothing here is a shortcut around a rule. The
identity quarantine is genuinely resolved through the owner-only path, and the detector
genuinely evaluates its eight conditions. Guarded to local/demo like every seed command.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.exceptions.detectors import revenue_unbilled as detector
from apps.exceptions.models import ExceptionCase
from apps.exceptions.services import runs
from apps.ingestion.models import DataSource, IdentityResolutionIssue
from apps.ingestion.services import coverage as coverage_service
from apps.ingestion.services import identity, reconciliation
from apps.ingestion.services import imports as import_service
from apps.operations.models import Site
from apps.organizations.management.commands._guards import refuse_outside_local_or_demo
from apps.organizations.models import Organization, User

FIXTURES = Path(settings.BASE_DIR) / "sample_data" / "atlas_facility_services"

#: filename, contract kind, source key, coverage record family, query contract
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


class Command(BaseCommand):
    help = "Import the Atlas fixtures, resolve identities, and run the detector."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--organization", default="atlas-facility-services")
        parser.add_argument("--as-of", default="2026-08-20T10:00:00+00:00")
        parser.add_argument("--run-key", default="demo")

    def handle(self, *args: Any, **options: Any) -> None:
        refuse_outside_local_or_demo("demo_load")

        organization = Organization.objects.filter(slug=options["organization"]).first()
        if organization is None:
            raise CommandError("Unknown organization. Run seed_demo first.")
        actor = (
            User.objects.filter(memberships__organization=organization).order_by("email").first()
        )
        if actor is None:
            raise CommandError("The organization has no members. Run seed_demo first.")

        as_of = dt.datetime.fromisoformat(options["as_of"])
        if as_of.tzinfo is None:
            raise CommandError("--as-of must include a UTC offset.")

        run = reconciliation.open_run(
            organization=organization, run_key=options["run_key"], as_of=as_of
        )

        for filename, kind, source_key, family, query_contract in PLAN:
            source = DataSource.objects.get(organization=organization, system_key=source_key)
            declaration = coverage_service.CoverageDeclaration(
                record_family=family,
                scope_type="organization",
                coverage_start_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                coverage_end_at=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
                query_contract_code=query_contract,
                query_contract_version=1,
                completeness="complete",
                declaration_basis="synthetic_fixture",
            )
            result = import_service.upload(
                organization=organization,
                source=source,
                kind=kind,
                filename=filename,
                payload=(FIXTURES / filename).read_bytes(),
                observation_mode="full_snapshot",
                source_as_of_at=as_of,
                declarations=[declaration],
                actor=actor,
            )
            if result.batch is None:
                raise CommandError(
                    f"{filename} was rejected: {[e.code for e in result.file_errors]}"
                )
            batch = import_service.commit(result.batch, actor)
            reconciliation.attach_batch(run, batch)
            self.stdout.write(
                f"  {filename:34} +{batch.created_count} ~{batch.updated_count} "
                f"={batch.unchanged_count} rejected={batch.invalid_row_count}"
            )

        quarantined = IdentityResolutionIssue.objects.filter(
            organization=organization, status=IdentityResolutionIssue.Status.UNRESOLVED
        )
        for issue in quarantined:
            identity.resolve_issue_manually(
                issue=issue,
                target=Site.objects.get(
                    organization=organization, name="Potomac Distribution Annex"
                ),
                resolved_by=actor,
                note="Resolved by demo_load for rehearsal.",
            )
            self.stdout.write(
                f"  resolved identity: {issue.entity_type}:{issue.supplied_external_id}"
            )

        run = reconciliation.evaluate_readiness(run)
        self.stdout.write(f"  reconciliation run: {run.status}")
        if not run.is_ready:
            raise CommandError(
                f"Run did not become ready: {reconciliation.readiness_blockers(run)}"
            )

        detector_run = runs.evaluate_and_persist(
            run=run, detector_code=detector.RULE_CODE, as_of=as_of
        )
        if detector_run is None:  # pragma: no cover - only if another worker holds the lease
            raise CommandError("A detector lease is held elsewhere; try again shortly.")
        self.stdout.write(
            f"  detector: scanned {detector_run.scanned_count}, created {detector_run.created_count}, "
            f"skipped {detector_run.skipped_count} {detector_run.skip_reasons}"
        )

        cases = ExceptionCase.objects.filter(organization=organization)
        self.stdout.write(self.style.SUCCESS(f"Demo ready: {cases.count()} case(s)."))
        for case in cases:
            snapshot = case.financial_snapshots.order_by("-snapshot_version").first()
            value = snapshot.candidate_value if snapshot else None
            title = case.work_order.title if case.work_order else "(no work order)"
            self.stdout.write(
                f"  {case.case_number}: {title} — "
                f"candidate {value if value is not None else 'manual amount required'}"
            )
        self.stdout.write("Sign in at http://127.0.0.1:8000/ as finance@atlas.example")
