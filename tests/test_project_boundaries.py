"""Boundary tests.

These encode the non-negotiable constraints from Part I of the master prompt so a
later change cannot quietly cross them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings

PROJECT_ROOT = Path(settings.BASE_DIR)

# Application source only. The tests directory is excluded deliberately: this module
# contains the forbidden strings as literals and would otherwise match itself.
PYTHON_SOURCES = [
    path
    for root in ("apps", "config")
    for path in (PROJECT_ROOT / root).rglob("*.py")
    if "migrations" not in path.parts
]


def test_external_actions_are_disabled() -> None:
    assert settings.EXTERNAL_ACTIONS_ENABLED is False


def test_evidence_mode_is_metadata_only() -> None:
    assert settings.EVIDENCE_MODE == "metadata_only"


def test_no_source_file_imports_a_v1_module() -> None:
    """V1 must never be imported at runtime (section 3.2).

    Matches genuine top-level import statements for V1's module names, rather than
    a substring (which would flag `from config.celery import app as celery_app`).
    """
    v1_modules = ("app", "db", "ai_parser", "sms", "seed", "shiftcare", "simulate_day")
    names = "|".join(v1_modules)
    import_pattern = re.compile(
        rf"^\s*(?:from\s+({names})(?:\.[\w.]+)?\s+import\b|import\s+({names})(?:\s|,|$))"
    )

    offenders = []
    for path in PYTHON_SOURCES:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if import_pattern.match(line):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, f"Possible V1 import: {offenders}"


def test_v1_import_detector_actually_detects() -> None:
    """The detector above must not be vacuous."""
    v1_modules = ("app", "db", "ai_parser", "sms", "seed", "shiftcare", "simulate_day")
    names = "|".join(v1_modules)
    import_pattern = re.compile(
        rf"^\s*(?:from\s+({names})(?:\.[\w.]+)?\s+import\b|import\s+({names})(?:\s|,|$))"
    )
    assert import_pattern.match("from db import get_connection")
    assert import_pattern.match("import sms")
    assert import_pattern.match("from ai_parser import parse")
    # Must NOT match legitimate V2 imports.
    assert not import_pattern.match("from config.celery import app as celery_app")
    assert not import_pattern.match("from apps.common.models import TimestampedModel")
    assert not import_pattern.match("from django.db import models")


def test_no_dotenv_loader_is_used() -> None:
    """Section 33.1: test settings must ignore root dotenv files.

    The project loads no dotenv at all, so a V1 .env cannot leak in through any
    settings module.
    """
    offenders = [
        path.name
        for path in PYTHON_SOURCES
        if "load_dotenv" in path.read_text(encoding="utf-8")
        or "from dotenv" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"dotenv loading found in: {offenders}"


def test_no_messaging_provider_dependency_is_declared() -> None:
    """No SMS/email provider may exist in the demo (section 20)."""
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    for provider in ("twilio", "telnyx", "vonage", "sendgrid", "boto3", "anthropic", "openai"):
        assert provider not in pyproject, f"Unexpected provider dependency: {provider}"


def test_env_example_contains_no_provider_variables() -> None:
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").upper()
    for name in ("TWILIO", "TELNYX", "VONAGE", "SMS_", "ANTHROPIC_API_KEY", "OPENAI"):
        assert name not in example, f"Provider variable leaked into .env.example: {name}"


def test_env_example_has_no_assigned_secret_values() -> None:
    """Only names and safe examples are permitted (section 20.1)."""
    lines = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    for line in lines:
        if line.strip().startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() in {"DJANGO_SECRET_KEY", "SENTRY_DSN"}:
            assert value.strip() == "", f"{key} must have no value in .env.example"


def test_settings_time_zone_is_utc() -> None:
    """Instants are stored as timezone-aware UTC (section 18)."""
    assert settings.TIME_ZONE == "UTC"
    assert settings.USE_TZ is True


def test_whitenoise_follows_security_middleware() -> None:
    middleware = list(settings.MIDDLEWARE)
    security = middleware.index("django.middleware.security.SecurityMiddleware")
    whitenoise = middleware.index("whitenoise.middleware.WhiteNoiseMiddleware")
    assert whitenoise == security + 1


def test_storages_defines_both_required_keys() -> None:
    """Django 5.2 does not merge STORAGES with defaults."""
    assert set(settings.STORAGES) >= {"default", "staticfiles"}


def test_celery_registers_exactly_the_phase_four_tasks() -> None:
    """Phase 4 registers three tasks and nothing else.

    No attendance/quality detector task, no messaging task, no export task may exist.
    """
    from config import celery_app

    celery_app.loader.import_default_modules()
    registered = {name for name in celery_app.tasks if not name.startswith("celery.")}
    assert registered == {
        "apps.exceptions.tasks.run_detector",
        "apps.exceptions.tasks.sweep_dispatch_intents",
        "apps.exceptions.tasks.schedule_detectors",
    }, registered


def test_celery_is_configured_for_redelivery_safety() -> None:
    assert settings.CELERY_TASK_ACKS_LATE is True
    assert settings.CELERY_TASK_REJECT_ON_WORKER_LOST is True


@pytest.mark.parametrize(
    "path", ["docs/BUILD_STATUS.md", "docs/THREAT_MODEL.md", ".env.example", "compose.yaml"]
)
def test_required_phase_one_artifacts_exist(path: str) -> None:
    assert (PROJECT_ROOT / path).is_file(), f"Missing required Phase 1 artifact: {path}"
