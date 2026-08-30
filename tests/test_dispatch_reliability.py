"""Dispatch intents, the sweeper, leases, and the crash boundary (sections 19, 22.3, 22.5).

The crash test is the important one: it exercises the boundary itself — the intent is
committed, the broker publish raises, and the sweeper must recover — rather than mocking
a component that assumes the boundary was survived.
"""

from __future__ import annotations

import datetime as dt
from unittest import mock

import pytest
from django.utils import timezone

from apps.exceptions.detectors import revenue_unbilled as det
from apps.exceptions.models import (
    DetectorDispatchIntent,
    DetectorRun,
    DetectorScheduleLease,
    ExceptionCase,
)
from apps.exceptions.services import dispatch, runs
from apps.exceptions.tasks import run_detector
from tests.phase4_helpers import AS_OF, load_atlas, seed_atlas

pytestmark = pytest.mark.django_db


@pytest.fixture
def atlas(settings):  # type: ignore[no-untyped-def]
    settings.APP_ENV = "local"
    organization, actor = seed_atlas()
    return load_atlas(organization, actor)


class TestIntentsAreCreatedAtReadiness:
    def test_readiness_inserts_exactly_one_intent_per_enabled_detector(self, atlas) -> None:  # type: ignore[no-untyped-def]
        assert atlas.run.is_ready
        intents = DetectorDispatchIntent.objects.filter(reconciliation_run=atlas.run)
        assert intents.count() == len(dispatch.ENABLED_DETECTORS) == 1
        intent = intents.get()
        assert intent.detector_code == det.RULE_CODE
        assert intent.input_manifest_sha256 == atlas.run.input_manifest_sha256

    def test_readiness_is_idempotent_for_intents(self, atlas) -> None:  # type: ignore[no-untyped-def]
        from apps.ingestion.services import reconciliation

        reconciliation.evaluate_readiness(atlas.run)
        dispatch.create_intents(atlas.run)  # a second explicit call
        assert DetectorDispatchIntent.objects.filter(reconciliation_run=atlas.run).count() == 1

    def test_intent_is_unique_per_evaluation(self, atlas) -> None:  # type: ignore[no-untyped-def]
        from django.db import IntegrityError, transaction

        intent = DetectorDispatchIntent.objects.get(reconciliation_run=atlas.run)
        with pytest.raises(IntegrityError), transaction.atomic():
            DetectorDispatchIntent.objects.create(
                organization=atlas.organization,
                reconciliation_run=atlas.run,
                detector_code=intent.detector_code,
                rule_version=intent.rule_version,
                input_manifest_sha256=intent.input_manifest_sha256,
            )


class TestPublishAndSweep:
    def test_publish_claims_then_marks_published(self, atlas) -> None:  # type: ignore[no-untyped-def]
        intent = DetectorDispatchIntent.objects.get(reconciliation_run=atlas.run)
        intent.status = DetectorDispatchIntent.Status.PENDING  # the on-commit nudge may have run
        intent.save()
        with mock.patch("apps.exceptions.services.dispatch._publish", return_value="task-123"):
            result = dispatch.publish_intent(intent.id)
        assert result is not None
        assert result.status == DetectorDispatchIntent.Status.PUBLISHED
        assert result.broker_task_id == "task-123"
        assert result.attempts == 1

    def test_second_publish_of_a_published_intent_does_nothing(self, atlas) -> None:  # type: ignore[no-untyped-def]
        intent = DetectorDispatchIntent.objects.get(reconciliation_run=atlas.run)
        intent.status = DetectorDispatchIntent.Status.PENDING
        intent.save()
        with mock.patch("apps.exceptions.services.dispatch._publish", return_value="t1") as publish:
            dispatch.publish_intent(intent.id)
            assert dispatch.publish_intent(intent.id) is None
        assert publish.call_count == 1

    def test_crash_after_commit_before_publish_is_recovered_by_the_sweeper(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Line 2597. The intent row is durable; the publish raises; the sweeper retries."""
        intent = DetectorDispatchIntent.objects.get(reconciliation_run=atlas.run)
        intent.status = DetectorDispatchIntent.Status.PENDING
        intent.save()

        # 1. The publish crashes AFTER the claim commits.
        with mock.patch(
            "apps.exceptions.services.dispatch._publish", side_effect=ConnectionError("broker down")
        ):
            with pytest.raises(ConnectionError):
                dispatch.publish_intent(intent.id)
        intent.refresh_from_db()
        assert intent.status == DetectorDispatchIntent.Status.PUBLISHING
        assert intent.error_code == "ConnectionError"
        assert intent.attempts == 1

        # 2. While the lease is live, the sweeper must NOT double-claim it.
        with mock.patch("apps.exceptions.services.dispatch._publish", return_value="t2") as publish:
            assert dispatch.sweep() == 0
            assert publish.call_count == 0

        # 3. After the lease expires, the sweeper recovers and publishes.
        DetectorDispatchIntent.objects.filter(id=intent.id).update(
            leased_until=timezone.now() - dt.timedelta(seconds=1)
        )
        with mock.patch("apps.exceptions.services.dispatch._publish", return_value="t2"):
            assert dispatch.sweep() == 1
        intent.refresh_from_db()
        assert intent.status == DetectorDispatchIntent.Status.PUBLISHED
        assert intent.attempts == 2
        assert intent.error_code == ""

    def test_duplicate_delivery_yields_one_detector_run_and_one_case(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """At-least-once delivery: the task can arrive twice; the evaluation key dedups."""
        intent = DetectorDispatchIntent.objects.get(reconciliation_run=atlas.run)
        first = run_detector.apply(args=[str(intent.id)]).get()
        second = run_detector.apply(args=[str(intent.id)]).get()
        assert first == "succeeded"
        assert second == "succeeded"
        assert DetectorRun.objects.filter(reconciliation_run=atlas.run).count() == 1
        assert ExceptionCase.objects.count() == 1

    def test_unknown_intent_is_reported_not_raised(self) -> None:
        import uuid

        assert run_detector.apply(args=[str(uuid.uuid4())]).get() == "missing_intent"


class TestDetectorRunLease:
    def test_concurrent_claim_of_a_live_lease_returns_none(self, atlas) -> None:  # type: ignore[no-untyped-def]
        first = runs.claim(
            run=atlas.run, detector_code=det.RULE_CODE, rule_version=det.RULE_VERSION, as_of=AS_OF
        )
        assert first is not None and first.status == DetectorRun.Status.RUNNING
        second = runs.claim(
            run=atlas.run, detector_code=det.RULE_CODE, rule_version=det.RULE_VERSION, as_of=AS_OF
        )
        assert second is None

    def test_expired_lease_is_reclaimed_with_attempt_increment(self, atlas) -> None:  # type: ignore[no-untyped-def]
        first = runs.claim(
            run=atlas.run, detector_code=det.RULE_CODE, rule_version=det.RULE_VERSION, as_of=AS_OF
        )
        DetectorRun.objects.filter(pk=first.pk).update(
            leased_until=timezone.now() - dt.timedelta(seconds=1)
        )
        second = runs.claim(
            run=atlas.run, detector_code=det.RULE_CODE, rule_version=det.RULE_VERSION, as_of=AS_OF
        )
        assert second is not None and second.pk == first.pk
        assert second.attempt_count == 2
        assert second.lease_owner_id != first.lease_owner_id

    def test_a_stale_owner_cannot_persist(self, atlas) -> None:  # type: ignore[no-untyped-def]
        first = runs.claim(
            run=atlas.run, detector_code=det.RULE_CODE, rule_version=det.RULE_VERSION, as_of=AS_OF
        )
        DetectorRun.objects.filter(pk=first.pk).update(
            leased_until=timezone.now() - dt.timedelta(seconds=1)
        )
        runs.claim(
            run=atlas.run, detector_code=det.RULE_CODE, rule_version=det.RULE_VERSION, as_of=AS_OF
        )  # reclaimed
        output = det.evaluate(atlas.run, as_of=AS_OF)
        with pytest.raises(runs.NotLeaseOwner):
            runs.persist(first, output)  # `first` still carries the OLD owner id
        assert ExceptionCase.objects.count() == 0

    def test_a_stale_owner_cannot_heartbeat(self, atlas) -> None:  # type: ignore[no-untyped-def]
        first = runs.claim(
            run=atlas.run, detector_code=det.RULE_CODE, rule_version=det.RULE_VERSION, as_of=AS_OF
        )
        DetectorRun.objects.filter(pk=first.pk).update(lease_owner_id="someone-else")
        with pytest.raises(runs.NotLeaseOwner):
            runs.heartbeat(first)

    def test_a_finished_run_is_returned_not_re_evaluated(self, atlas) -> None:  # type: ignore[no-untyped-def]
        done = runs.evaluate_and_persist(run=atlas.run, detector_code=det.RULE_CODE, as_of=AS_OF)
        again = runs.evaluate_and_persist(run=atlas.run, detector_code=det.RULE_CODE, as_of=AS_OF)
        assert again is not None and again.pk == done.pk
        assert DetectorRun.objects.count() == 1

    def test_a_failing_detector_records_a_failed_run(self, atlas) -> None:  # type: ignore[no-untyped-def]
        with (
            mock.patch.object(det, "evaluate", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError),
        ):
            runs.evaluate_and_persist(run=atlas.run, detector_code=det.RULE_CODE, as_of=AS_OF)
        run = DetectorRun.objects.get()
        assert run.status == DetectorRun.Status.FAILED
        assert run.failure_code == "RuntimeError"
        assert "boom" not in run.failure_summary  # the message is not copied verbatim


class TestScheduleLease:
    def test_two_schedulers_one_window_one_lease(self, atlas) -> None:  # type: ignore[no-untyped-def]
        window = dispatch.run_window(
            organization=atlas.organization, cadence_minutes=1440, at=AS_OF
        )
        first = dispatch.claim_schedule_lease(
            organization=atlas.organization,
            detector_code=det.RULE_CODE,
            rule_version=det.RULE_VERSION,
            window=window,
        )
        second = dispatch.claim_schedule_lease(
            organization=atlas.organization,
            detector_code=det.RULE_CODE,
            rule_version=det.RULE_VERSION,
            window=window,
        )
        assert first is not None
        assert second is None
        assert DetectorScheduleLease.objects.count() == 1

    def test_windows_are_deterministic_in_organization_time(self, atlas) -> None:  # type: ignore[no-untyped-def]
        a = dispatch.run_window(organization=atlas.organization, cadence_minutes=1440, at=AS_OF)
        b = dispatch.run_window(
            organization=atlas.organization, cadence_minutes=1440, at=AS_OF + dt.timedelta(hours=3)
        )
        assert a == b
        assert a[1] - a[0] == dt.timedelta(days=1)

    def test_schedule_lease_does_not_substitute_for_run_uniqueness(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Line 713: a corrected manifest in the SAME window gets its own evaluation."""
        from apps.ingestion.models import ReconciliationRun

        runs.evaluate_and_persist(run=atlas.run, detector_code=det.RULE_CODE, as_of=AS_OF)
        corrected = ReconciliationRun.objects.create(
            organization=atlas.organization,
            run_key="corrected",
            as_of=AS_OF,
            status="ready",
            became_ready_at=AS_OF,
            input_manifest_sha256="e" * 64,
        )
        for run_input in atlas.run.inputs.all():
            clone = corrected.inputs.create(
                organization=atlas.organization,
                domain=run_input.domain,
                import_batch=run_input.import_batch,
            )
            clone.coverage_declarations.set(run_input.coverage_declarations.all())
        runs.evaluate_and_persist(run=corrected, detector_code=det.RULE_CODE, as_of=AS_OF)
        assert DetectorRun.objects.count() == 2  # two evaluations...
        assert ExceptionCase.objects.count() == 1  # ...one case


class TestPhaseBoundaries:
    def test_only_the_revenue_detector_is_enabled(self) -> None:
        assert [c for c, _ in dispatch.ENABLED_DETECTORS] == [det.RULE_CODE]

    def test_no_attendance_or_quality_detector_module_exists(self) -> None:
        import importlib

        for name in ("attendance_no_check_in", "quality_correction_due"):
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(f"apps.exceptions.detectors.{name}")

    def test_no_journey_a_or_c_tables(self) -> None:
        """Route B ships approvals and a finance export; it must ship nothing else.

        Phase 6 legitimately created `recovery_approval`, `recovery_finance_export` and
        `recovery_financial_stage_event`. The boundary that still holds is Journey A
        and Journey C: no recommendation engine, no proposed external action, no
        evidence artifacts, and no draft handoff, through Phase 8.
        """
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
            tables = {r[0] for r in cursor.fetchall()}
        for forbidden in (
            "recommendation",
            "proposed_action",
            "evidence_artifact",
            "handoff",
            "notification",
            "client_message",
        ):
            assert not any(forbidden in t for t in tables), forbidden
        # Positive control: the guard is only meaningful if it can see real tables.
        assert "recovery_finance_export" in tables

    def test_retry_backoff_stays_under_the_visibility_timeout(self, settings) -> None:  # type: ignore[no-untyped-def]
        assert (
            run_detector.retry_backoff_max
            < settings.CELERY_BROKER_TRANSPORT_OPTIONS["visibility_timeout"]
        )
