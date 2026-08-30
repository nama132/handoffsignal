"""Configuration contract tests (master prompt section 20.1).

Covers: APP_ENV allowlisting, SQLite rejection, Redis URL validation, wildcard host
rejection, development-secret rejection, the Phase 8 side-effect boundary, and the
test-database guard.
"""

from __future__ import annotations

import pytest

from config import env
from config.dbguard import assert_test_database


class TestAppEnv:
    def test_unknown_app_env_fails_startup(self, monkeypatch) -> None:
        monkeypatch.setenv("APP_ENV", "staging")
        with pytest.raises(env.ConfigurationError) as exc:
            env.get_app_env()
        assert "APP_ENV" in str(exc.value)

    def test_known_app_envs_are_accepted(self, monkeypatch) -> None:
        for value in ("local", "test", "demo", "pilot"):
            monkeypatch.setenv("APP_ENV", value)
            assert env.get_app_env() == value


class TestDatabaseUrl:
    def test_sqlite_is_rejected(self) -> None:
        with pytest.raises(env.ConfigurationError) as exc:
            env.parse_database_url("sqlite:///db.sqlite3")
        assert "SQLite" in str(exc.value)

    def test_file_scheme_is_rejected(self) -> None:
        with pytest.raises(env.ConfigurationError):
            env.parse_database_url("file:///tmp/db")

    def test_mysql_is_rejected(self) -> None:
        with pytest.raises(env.ConfigurationError):
            env.parse_database_url("mysql://u:p@h:3306/d")

    def test_empty_is_rejected(self) -> None:
        with pytest.raises(env.ConfigurationError):
            env.parse_database_url("")

    def test_missing_database_name_is_rejected(self) -> None:
        with pytest.raises(env.ConfigurationError):
            env.parse_database_url("postgresql://u:p@localhost:5432/")

    def test_postgres_url_parses(self) -> None:
        config = env.parse_database_url(
            "postgresql://user:pass@127.0.0.1:5433/opsrecovery_v2?sslmode=prefer"
        )
        assert config["ENGINE"] == "django.db.backends.postgresql"
        assert config["NAME"] == "opsrecovery_v2"
        assert config["USER"] == "user"
        assert config["HOST"] == "127.0.0.1"
        assert config["PORT"] == "5433"
        assert config["OPTIONS"] == {"sslmode": "prefer"}

    def test_percent_encoded_password_is_decoded(self) -> None:
        config = env.parse_database_url("postgresql://u:p%40ss%2Fword@h:5432/d")
        assert config["PASSWORD"] == "p@ss/word"

    def test_error_message_never_contains_the_value(self) -> None:
        secret = "sup3rs3cret-token-value"
        with pytest.raises(env.ConfigurationError) as exc:
            env.parse_database_url(f"mysql://user:{secret}@host:3306/db")
        assert secret not in str(exc.value)


class TestRedisUrl:
    def test_valid_url_accepted(self) -> None:
        assert env.validate_redis_url("redis://127.0.0.1:6380/1")

    @pytest.mark.parametrize("url", ["", "http://localhost:6379", "redis://"])
    def test_invalid_urls_rejected(self, url: str) -> None:
        with pytest.raises(env.ConfigurationError):
            env.validate_redis_url(url)


class TestDeploymentHardening:
    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "changeme",
            "django-insecure-local-development-key-not-for-deployment",
            "short-key",
        ],
    )
    def test_insecure_secret_keys_are_rejected(self, value) -> None:
        with pytest.raises(env.ConfigurationError):
            env.validate_deployment_secret_key(value)

    def test_strong_secret_key_is_accepted(self) -> None:
        strong = "x" * 64
        assert env.validate_deployment_secret_key(strong) == strong

    def test_wildcard_host_is_rejected(self) -> None:
        with pytest.raises(env.ConfigurationError):
            env.require_no_wildcard(["*"], variable_name="DJANGO_ALLOWED_HOSTS")

    def test_empty_host_list_is_rejected(self) -> None:
        with pytest.raises(env.ConfigurationError):
            env.require_no_wildcard([], variable_name="DJANGO_ALLOWED_HOSTS")

    @pytest.mark.parametrize("origin", ["http://example.com", "https://*.example.com", "not-a-url"])
    def test_non_https_or_wildcard_origins_rejected(self, origin: str) -> None:
        with pytest.raises(env.ConfigurationError):
            env.validate_https_origin(origin, variable_name="APP_BASE_URL")

    def test_https_origin_accepted_and_normalized(self) -> None:
        assert (
            env.validate_https_origin("https://demo.example.com/", variable_name="APP_BASE_URL")
            == "https://demo.example.com"
        )


class TestPhaseBoundaries:
    def test_external_actions_enabled_is_rejected(self, monkeypatch) -> None:
        monkeypatch.setenv("EXTERNAL_ACTIONS_ENABLED", "true")
        with pytest.raises(env.ConfigurationError) as exc:
            env.validate_phase_boundaries("demo")
        assert "EXTERNAL_ACTIONS_ENABLED" in str(exc.value)

    def test_non_metadata_evidence_mode_is_rejected(self, monkeypatch) -> None:
        monkeypatch.setenv("EXTERNAL_ACTIONS_ENABLED", "false")
        monkeypatch.setenv("EVIDENCE_MODE", "blob_storage")
        with pytest.raises(env.ConfigurationError) as exc:
            env.validate_phase_boundaries("demo")
        assert "EVIDENCE_MODE" in str(exc.value)

    def test_demo_as_of_rejected_in_pilot(self, monkeypatch) -> None:
        monkeypatch.setenv("EXTERNAL_ACTIONS_ENABLED", "false")
        monkeypatch.setenv("EVIDENCE_MODE", "metadata_only")
        monkeypatch.setenv("DEMO_AS_OF", "2026-09-01T09:00:00-04:00")
        with pytest.raises(env.ConfigurationError):
            env.validate_phase_boundaries("pilot")

    def test_clean_environment_passes(self, monkeypatch) -> None:
        monkeypatch.setenv("EXTERNAL_ACTIONS_ENABLED", "false")
        monkeypatch.setenv("EVIDENCE_MODE", "metadata_only")
        monkeypatch.delenv("DEMO_AS_OF", raising=False)
        env.validate_phase_boundaries("demo")  # must not raise


class TestTestDatabaseGuard:
    def test_production_looking_name_is_refused(self) -> None:
        with pytest.raises(env.ConfigurationError):
            assert_test_database("opsrecovery_v2", "127.0.0.1")

    def test_remote_host_is_refused(self) -> None:
        with pytest.raises(env.ConfigurationError):
            assert_test_database("opsrecovery_v2_test", "db.production.example.com")

    def test_empty_name_is_refused(self) -> None:
        with pytest.raises(env.ConfigurationError):
            assert_test_database("", "127.0.0.1")

    @pytest.mark.parametrize(
        "name", ["opsrecovery_v2_test", "test_opsrecovery_v2", "opsrecovery_ci"]
    )
    def test_allowlisted_test_names_pass(self, name: str) -> None:
        assert_test_database(name, "127.0.0.1")

    def test_guard_message_does_not_disclose_the_name(self) -> None:
        with pytest.raises(env.ConfigurationError) as exc:
            assert_test_database("customer_production_db", "127.0.0.1")
        assert "customer_production_db" not in str(exc.value)


class TestBooleanParsing:
    @pytest.mark.parametrize("raw,expected", [("true", True), ("1", True), ("no", False)])
    def test_valid_booleans(self, monkeypatch, raw: str, expected: bool) -> None:
        monkeypatch.setenv("SOME_FLAG", raw)
        assert env.get_bool("SOME_FLAG", default=False) is expected

    def test_invalid_boolean_rejected(self, monkeypatch) -> None:
        monkeypatch.setenv("SOME_FLAG", "maybe")
        with pytest.raises(env.ConfigurationError):
            env.get_bool("SOME_FLAG", default=False)
