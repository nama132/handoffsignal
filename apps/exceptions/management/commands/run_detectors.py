"""Manually evaluate detectors against a ready reconciliation run.

Converges on the same DetectorRun row as the scheduled path: the unique evaluation
key means the manual command and the beat schedule can never evaluate one manifest
twice (section 19: "Keep one writer for a semantic action").
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.exceptions.services import dispatch, runs
from apps.ingestion.models import ReconciliationRun
from apps.organizations.models import Organization


class Command(BaseCommand):
    help = "Evaluate enabled detectors against a ready reconciliation run."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--organization", required=True, help="Organization slug.")
        parser.add_argument("--run-key", required=True)
        parser.add_argument(
            "--as-of", default="", help="ISO 8601 with offset; defaults to the run's as_of."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        organization = Organization.objects.filter(slug=options["organization"]).first()
        if organization is None:
            raise CommandError("Unknown organization.")
        run = ReconciliationRun.objects.filter(
            organization=organization, run_key=options["run_key"]
        ).first()
        if run is None:
            raise CommandError("Unknown run key for this organization.")
        if not run.is_ready:
            raise CommandError(f"Run is {run.status!r}; only a ready run can be evaluated.")

        as_of = dt.datetime.fromisoformat(options["as_of"]) if options["as_of"] else run.as_of
        if as_of.tzinfo is None:
            raise CommandError("--as-of must include a UTC offset.")

        for code, _version in dispatch.ENABLED_DETECTORS:
            result = runs.evaluate_and_persist(run=run, detector_code=code, as_of=as_of)
            if result is None:
                self.stdout.write(f"{code}: lease held by another worker; nothing done.")
                continue
            self.stdout.write(
                self.style.SUCCESS(
                    f"{code} v{result.rule_version}: {result.status} — scanned {result.scanned_count}, "
                    f"created {result.created_count}, refreshed {result.updated_count}, "
                    f"skipped {result.skipped_count} {result.skip_reasons}"
                )
            )
