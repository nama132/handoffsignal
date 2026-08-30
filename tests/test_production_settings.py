"""Production settings must refuse insecure input at startup.

Settings validation happens at import time, so each case is exercised in a fresh
subprocess with a controlled environment. This proves the real module fails — not
just the helper functions it calls.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

STRONG_KEY = "s" * 64

VALID_ENV = {
    "APP_ENV": "demo",
    "DJANGO_SECRET_KEY": STRONG_KEY,
    "DJANGO_ALLOWED_HOSTS": "demo.example.com",
    "DJANGO_CSRF_TRUSTED_ORIGINS": "https://demo.example.com",
    "APP_BASE_URL": "https://demo.example.com",
    "DATABASE_URL": "postgresql://u:p@127.0.0.1:5432/opsrecovery_v2",
    "REDIS_URL": "redis://127.0.0.1:6380/0",
    "EXTERNAL_ACTIONS_ENABLED": "false",
    "EVIDENCE_MODE": "metadata_only",
    "LOG_LEVEL": "INFO",
}

_IMPORT_SNIPPET = (
    "import django;"
    "from django.conf import settings;"
    "django.setup();"
    "print('DEBUG=%s' % settings.DEBUG);"
    "print('HOSTS=%s' % settings.ALLOWED_HOSTS);"
    "print('SSL=%s' % settings.SECURE_SSL_REDIRECT);"
    "print('SESSION_SECURE=%s' % settings.SESSION_COOKIE_SECURE);"
    "print('EXTERNAL=%s' % settings.EXTERNAL_ACTIONS_ENABLED);"
    "print('STATICSTORAGE=%s' % settings.STORAGES['staticfiles']['BACKEND'])"
)


def _load_production(env_overrides: dict[str, str], *, remove: list[str] | None = None):
    env = dict(VALID_ENV)
    env.update(env_overrides)
    for key in remove or []:
        env.pop(key, None)
    env["DJANGO_SETTINGS_MODULE"] = "config.settings.production"
    env["PATH"] = "/usr/bin:/bin"
    return subprocess.run(
        [sys.executable, "-c", _IMPORT_SNIPPET],
        capture_output=True,
        text=True,
        env=env,
        timeout=90,
    )


def test_valid_production_environment_loads() -> None:
    result = _load_production({})
    assert result.returncode == 0, result.stderr
    assert "DEBUG=False" in result.stdout
    assert "SSL=True" in result.stdout
    assert "SESSION_SECURE=True" in result.stdout
    assert "EXTERNAL=False" in result.stdout
    assert "CompressedManifestStaticFilesStorage" in result.stdout


@pytest.mark.parametrize(
    "label,overrides,removes",
    [
        ("missing secret key", {}, ["DJANGO_SECRET_KEY"]),
        (
            "development secret key",
            {"DJANGO_SECRET_KEY": "django-insecure-local-development-key-not-for-deployment"},
            [],
        ),
        ("short secret key", {"DJANGO_SECRET_KEY": "tooshort"}, []),
        ("wildcard allowed hosts", {"DJANGO_ALLOWED_HOSTS": "*"}, []),
        ("missing allowed hosts", {}, ["DJANGO_ALLOWED_HOSTS"]),
        ("http csrf origin", {"DJANGO_CSRF_TRUSTED_ORIGINS": "http://demo.example.com"}, []),
        ("wildcard csrf origin", {"DJANGO_CSRF_TRUSTED_ORIGINS": "https://*.example.com"}, []),
        ("http base url", {"APP_BASE_URL": "http://demo.example.com"}, []),
        ("missing base url", {}, ["APP_BASE_URL"]),
        ("sqlite database", {"DATABASE_URL": "sqlite:///db.sqlite3"}, []),
        ("missing database url", {}, ["DATABASE_URL"]),
        ("external actions enabled", {"EXTERNAL_ACTIONS_ENABLED": "true"}, []),
        ("evidence upload enabled", {"EVIDENCE_MODE": "blob_storage"}, []),
        ("debug enabled", {"DJANGO_DEBUG": "true"}, []),
        ("unknown app env", {"APP_ENV": "staging"}, []),
        ("local app env in production settings", {"APP_ENV": "local"}, []),
        ("invalid log level", {"LOG_LEVEL": "TRACE"}, []),
    ],
)
def test_insecure_production_input_is_rejected(
    label: str, overrides: dict[str, str], removes: list[str]
) -> None:
    result = _load_production(overrides, remove=removes)
    assert result.returncode != 0, f"{label}: production settings loaded but should not have"
    assert "ConfigurationError" in result.stderr or "ImproperlyConfigured" in result.stderr, (
        f"{label}: unexpected failure mode:\n{result.stderr[-2000:]}"
    )


def test_failure_message_never_prints_a_secret_value() -> None:
    """Startup validation reports variable NAMES only (section 20.1)."""
    marker = "SUPERSECRETVALUE12345"
    result = _load_production({"DATABASE_URL": f"mysql://user:{marker}@host:3306/db"})
    assert result.returncode != 0
    assert marker not in result.stderr
    assert marker not in result.stdout
