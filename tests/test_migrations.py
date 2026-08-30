"""Migration integrity.

Section 19 forbids runtime DDL; every schema change must be an explicit migration.
These tests catch drift between models and migrations, and prove the schema applies
to an empty PostgreSQL database.
"""

from __future__ import annotations

import io

import pytest
from django.core.management import call_command
from django.db import connection


@pytest.mark.django_db
def test_no_migration_drift() -> None:
    """makemigrations --check must find nothing outstanding."""
    out = io.StringIO()
    try:
        call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
    except SystemExit as exc:  # non-zero exit means drift
        pytest.fail(f"Model changes are not reflected in migrations:\n{out.getvalue()}")
        raise exc


@pytest.mark.django_db
def test_schema_applies_to_a_fresh_database() -> None:
    """The user table exists after migrating an empty database."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            ["organizations_user"],
        )
        assert cursor.fetchone() is not None


@pytest.mark.django_db
def test_database_is_postgresql() -> None:
    """SQLite is rejected everywhere; the test run must be on PostgreSQL."""
    assert connection.vendor == "postgresql"


@pytest.mark.django_db
def test_user_primary_key_is_uuid_in_the_database() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'organizations_user' AND column_name = 'id'"
        )
        assert cursor.fetchone()[0] == "uuid"


@pytest.mark.django_db
def test_email_has_a_unique_constraint() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FROM pg_indexes
            WHERE tablename = 'organizations_user' AND indexdef ILIKE '%%UNIQUE%%email%%'
            """
        )
        assert cursor.fetchone()[0] >= 1


def test_only_expected_apps_have_migrations() -> None:
    """Phase 1 introduces one app migration set; Phase 2 models must not leak in."""
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(None, ignore_no_migrations=True)
    v2_apps = {
        app for app, _ in loader.disk_migrations if app.startswith(("organizations", "common"))
    }
    assert v2_apps == {"organizations"}, (
        f"Phase 1 defines migrations for the organizations app only; found: {sorted(v2_apps)}"
    )


@pytest.mark.django_db
def test_no_phase_five_or_six_tables_exist_yet() -> None:
    """Guards against shipping Phase 5 recommendation/handoff or Phase 6 approval/export
    models early. Route B skips Phase 5 entirely, so those must never appear."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = {row[0] for row in cursor.fetchall()}
    allowed_recovery_tables = {
        # Phase 6, Route B revenue slice.
        "recovery_approval",
        "recovery_finance_export",
        "recovery_finance_export_items",
        "recovery_financial_stage_event",
    }
    premature = {
        t
        for t in tables
        if any(
            marker in t
            for marker in (
                "recommendation",
                "candidate_assessment",
                "decision_scope",
                "proposed_action",
                "evidence_artifact",
                "handoff",
                "recovery_",
            )
        )
        and not t.startswith("exceptions_financial_recovery_item")
        and t not in allowed_recovery_tables
    }
    assert not premature, f"Unexpected later-phase tables present: {sorted(premature)}"


@pytest.mark.django_db
def test_phase_four_tables_are_present() -> None:
    """Positive control for the guard above."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = {row[0] for row in cursor.fetchall()}
    expected = {
        "exceptions_detector_dispatch_intent",
        "exceptions_detector_run",
        "exceptions_detector_schedule_lease",
        "exceptions_exception_case",
        "exceptions_exception_event",
        "exceptions_exception_source_link",
        "exceptions_financial_impact_snapshot",
        "exceptions_financial_recovery_item",
        "audit_event",
    }
    assert expected <= tables, f"Missing Phase 4 tables: {sorted(expected - tables)}"


@pytest.mark.django_db
def test_phase_three_tables_are_present() -> None:
    """Positive control: the guard above must not pass by an empty database."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = {row[0] for row in cursor.fetchall()}
    expected = {
        "ingestion_import_batch",
        "ingestion_import_coverage",
        "ingestion_import_row",
        "ingestion_source_record_version",
        "ingestion_reconciliation_run",
        "ingestion_reconciliation_run_input",
    }
    assert expected <= tables, f"Missing Phase 3 tables: {sorted(expected - tables)}"


@pytest.mark.django_db
def test_phase_two_tables_are_present() -> None:
    """Positive control: the guard above must not pass by an empty database."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = {row[0] for row in cursor.fetchall()}
    expected = {
        "organizations_organization",
        "organizations_membership",
        "organizations_membership_role_grant",
        "organizations_membership_site_grant",
        "operations_customer_account",
        "operations_site",
        "operations_contract",
        "operations_contract_site",
        "operations_service_obligation",
        "operations_work_order",
        "operations_accounting_invoice",
        "operations_accounting_payment",
        "ingestion_data_source",
        "ingestion_external_entity_reference",
        "ingestion_identity_resolution_issue",
        "ingestion_source_precedence_rule",
        "ingestion_reconciliation_issue",
    }
    assert expected <= tables, f"Missing Phase 2 tables: {sorted(expected - tables)}"


@pytest.mark.django_db
def test_route_b_omitted_models_have_no_tables() -> None:
    """Route B omits worker/shift/time/quality entirely — not even a placeholder."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = {row[0] for row in cursor.fetchall()}
    forbidden = {
        "operations_worker",
        "operations_shift",
        "operations_time_entry",
        "operations_quality_event",
        "operations_qualification_type",
        "operations_site_requirement",
        "operations_worker_qualification",
        "operations_worker_site_authorization",
        "operations_worker_availability_window",
        "operations_site_operational_rule",
    }
    present = tables & forbidden
    assert not present, f"Journey A/C models must not exist under Route B: {sorted(present)}"
