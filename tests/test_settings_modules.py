"""In-process import tests for the local and production settings modules.

tests/test_production_settings.py proves the modules behave correctly when loaded by
a real interpreter, which is the stronger guarantee but is invisible to coverage
because it runs in a subprocess. These tests import the same modules in-process so
their logic is measured and their asserted properties are pinned.
"""

from __future__ import annotations

import importlib
import os
from unittest import mock

import pytest

from config import env

STRONG_KEY = "p" * 64

PRODUCTION_ENV = {
    "APP_ENV": "demo",
    "DJANGO_SECRET_KEY": STRONG_KEY,
    "DJANGO_ALLOWED_HOSTS": "demo.example.com,alt.example.com",
    "DJANGO_CSRF_TRUSTED_ORIGINS": "https://demo.example.com",
    "APP_BASE_URL": "https://demo.example.com",
    "DATABASE_URL": "postgresql://u:p@127.0.0.1:5432/opsrecovery_v2",
    "REDIS_URL": "redis://127.0.0.1:6380/0",
    "EXTERNAL_ACTIONS_ENABLED": "false",
    "EVIDENCE_MODE": "metadata_only",
    "LOG_LEVEL": "INFO",
}


def _reload(module_name: str, environ: dict[str, str]):
    """Reload a settings module under a controlled environment.

    `from .base import *` does not re-execute base.py when it is already in
    sys.modules, so base must be reloaded first or values such as APP_ENV stay stale
    from whichever settings module the test session imported first.
    """
    with mock.patch.dict(os.environ, environ, clear=False):
        importlib.reload(importlib.import_module("config.settings.base"))
        module = importlib.import_module(module_name)
        return importlib.reload(module)


class TestLocalSettings:
    def test_local_settings_are_development_shaped(self) -> None:
        local = _reload("config.settings.local", {"APP_ENV": "local"})
        assert local.DEBUG is True
        assert "127.0.0.1" in local.ALLOWED_HOSTS
        # Development runs over plain HTTP, so Secure cookies would break sign-in.
        assert local.SESSION_COOKIE_SECURE is False
        assert local.CSRF_COOKIE_SECURE is False
        assert local.SECURE_SSL_REDIRECT is False

    def test_local_settings_still_forbid_external_actions(self) -> None:
        local = _reload("config.settings.local", {"APP_ENV": "local"})
        assert local.EXTERNAL_ACTIONS_ENABLED is False
        assert local.EVIDENCE_MODE == "metadata_only"

    def test_local_settings_never_use_sqlite(self) -> None:
        local = _reload("config.settings.local", {"APP_ENV": "local"})
        assert local.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"

    def test_local_email_backend_does_not_send(self) -> None:
        local = _reload("config.settings.local", {"APP_ENV": "local"})
        assert "locmem" in local.EMAIL_BACKEND


class TestProductionSettings:
    def test_valid_environment_produces_hardened_settings(self) -> None:
        prod = _reload("config.settings.production", PRODUCTION_ENV)
        assert prod.DEBUG is False
        assert prod.SECRET_KEY == STRONG_KEY
        assert prod.ALLOWED_HOSTS == ["demo.example.com", "alt.example.com"]
        assert prod.CSRF_TRUSTED_ORIGINS == ["https://demo.example.com"]
        assert prod.APP_BASE_URL == "https://demo.example.com"
        assert prod.SECURE_SSL_REDIRECT is True
        assert prod.SESSION_COOKIE_SECURE is True
        assert prod.CSRF_COOKIE_SECURE is True
        assert prod.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
        assert prod.EXTERNAL_ACTIONS_ENABLED is False
        assert prod.ALLOW_PUBLIC_DEMO_RESET is False

    def test_manifest_static_storage_is_used(self) -> None:
        prod = _reload("config.settings.production", PRODUCTION_ENV)
        assert "CompressedManifestStaticFilesStorage" in prod.STORAGES["staticfiles"]["BACKEND"]
        assert "default" in prod.STORAGES

    def test_hsts_is_off_until_explicitly_enabled(self) -> None:
        """HSTS must not be enabled before HTTPS is verified on the real domain."""
        prod = _reload("config.settings.production", PRODUCTION_ENV)
        assert prod.SECURE_HSTS_SECONDS == 0
        assert prod.SECURE_HSTS_INCLUDE_SUBDOMAINS is False

    def test_hsts_turns_on_when_configured(self) -> None:
        prod = _reload(
            "config.settings.production", {**PRODUCTION_ENV, "SECURE_HSTS_SECONDS": "31536000"}
        )
        assert prod.SECURE_HSTS_SECONDS == 31536000
        assert prod.SECURE_HSTS_INCLUDE_SUBDOMAINS is True
        assert prod.SECURE_HSTS_PRELOAD is False

    @pytest.mark.parametrize(
        "overrides",
        [
            {"APP_ENV": "local"},
            {"APP_ENV": "test"},
            {"DJANGO_SECRET_KEY": "django-insecure-local-development-key-not-for-deployment"},
            {"DJANGO_ALLOWED_HOSTS": "*"},
            {"DJANGO_CSRF_TRUSTED_ORIGINS": "http://demo.example.com"},
            {"APP_BASE_URL": "http://demo.example.com"},
            {"DATABASE_URL": "sqlite:///db.sqlite3"},
            {"EXTERNAL_ACTIONS_ENABLED": "true"},
            {"EVIDENCE_MODE": "blob_storage"},
            {"DJANGO_DEBUG": "true"},
        ],
    )
    def test_insecure_input_raises_on_import(self, overrides: dict[str, str]) -> None:
        with pytest.raises(env.ConfigurationError):
            _reload("config.settings.production", {**PRODUCTION_ENV, **overrides})


@pytest.fixture(autouse=True)
def _restore_test_settings():
    """Leave the settings modules as the test session found them."""
    yield
    with mock.patch.dict(os.environ, {"APP_ENV": "test"}, clear=False):
        importlib.reload(importlib.import_module("config.settings.base"))
        importlib.reload(importlib.import_module("config.settings.test"))
