"""Test-database guard.

Master prompt section 33.1: "A test run must refuse a database name/host that does
not match an allowlisted local/CI test pattern." This exists so a misconfigured
environment can never point the test runner at a real database.
"""

from __future__ import annotations

from config.env import ConfigurationError

# Hosts a test run may target. Anything else is refused.
ALLOWED_TEST_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "db", "postgres", ""})

# A test database name must contain one of these markers. Django's test runner
# prefixes the configured NAME with "test_", so both forms are accepted.
REQUIRED_TEST_NAME_MARKERS = ("test", "_ci")


def assert_test_database(name: str, host: str) -> None:
    """Refuse a database target that does not look like a disposable test database."""
    normalized_host = (host or "").strip().lower()
    if normalized_host not in ALLOWED_TEST_HOSTS:
        raise ConfigurationError(
            "Refusing to run tests: DATABASE_URL host is not an allowlisted local/CI "
            f"test host. Allowed: {sorted(h for h in ALLOWED_TEST_HOSTS if h)}."
        )

    normalized_name = (name or "").strip().lower()
    if not normalized_name:
        raise ConfigurationError("Refusing to run tests: DATABASE_URL names no database.")

    if not any(marker in normalized_name for marker in REQUIRED_TEST_NAME_MARKERS):
        raise ConfigurationError(
            "Refusing to run tests: the target database name does not match an "
            f"allowlisted test pattern {list(REQUIRED_TEST_NAME_MARKERS)}. "
            "The database name is not shown."
        )
