"""Environment parsing and startup validation.

Master prompt section 20.1 defines the V2 configuration contract. Two rules shape
every function here:

1. Fail closed. A missing or invalid value raises rather than falling back to a
   permissive default.
2. Never disclose a value. Error messages name the variable, never its content.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

# Environments the application recognises. Anything else fails startup.
APP_ENVS = ("local", "test", "demo", "pilot")

# Environments in which relaxed development defaults are permitted at all.
DEVELOPMENT_ENVS = ("local", "test")

# Known development secrets. Production/demo validation rejects these outright so a
# placeholder can never reach a deployed environment.
KNOWN_DEVELOPMENT_SECRET_KEYS = frozenset(
    {
        "django-insecure-local-development-key-not-for-deployment",
        "changeme",
        "secret",
        "insecure",
    }
)

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class ConfigurationError(Exception):
    """Raised when the environment cannot satisfy the configuration contract.

    The message names variables only. It must never contain a resolved value.
    """


def get_str(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    """Read a variable. An explicit default satisfies `required`."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        if default is not None:
            return default
        if required:
            raise ConfigurationError(f"{name} is required but missing or empty.")
        return None
    return raw.strip()


def get_bool(name: str, default: bool | None = None, *, required: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        if default is not None:
            return default
        if required:
            raise ConfigurationError(f"{name} is required but missing or empty.")
        raise ConfigurationError(f"{name} has no value and no default.")
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigurationError(f"{name} must be one of {sorted(_TRUE | _FALSE)} (value not shown).")


def get_choice(
    name: str, choices: tuple[str, ...], default: str | None = None, *, required: bool = True
) -> str:
    value = get_str(name, default, required=required)
    if value is None:
        raise ConfigurationError(f"{name} is required but missing or empty.")
    if value not in choices:
        raise ConfigurationError(
            f"{name} must be one of {list(choices)} (received value not shown)."
        )
    return value


def get_csv_list(name: str, *, required: bool = False) -> list[str]:
    raw = get_str(name, required=required)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def get_app_env() -> str:
    """Resolve APP_ENV. An unrecognised value fails startup (section 20.1)."""
    return get_choice("APP_ENV", APP_ENVS, default="local", required=True)


def parse_database_url(url: str, *, variable_name: str = "DATABASE_URL") -> dict[str, Any]:
    """Parse a PostgreSQL URL into a Django DATABASES entry.

    Uses only the standard library. SQLite is rejected in every environment
    (section 20.1: "V2 PostgreSQL only; SQLite rejected").
    """
    if not url or not url.strip():
        raise ConfigurationError(f"{variable_name} is required but missing or empty.")

    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()

    if scheme in ("sqlite", "sqlite3", "file"):
        raise ConfigurationError(
            f"{variable_name} names a SQLite database. V2 is PostgreSQL-only; "
            "SQLite is rejected in every environment."
        )
    if scheme not in ("postgres", "postgresql"):
        raise ConfigurationError(
            f"{variable_name} must use the postgres:// or postgresql:// scheme "
            "(received scheme not shown)."
        )

    name = unquote(parsed.path or "").lstrip("/")
    if not name:
        raise ConfigurationError(f"{variable_name} does not name a database.")

    try:
        port = parsed.port
    except ValueError as exc:  # non-numeric port
        raise ConfigurationError(f"{variable_name} has an invalid port.") from exc

    options: dict[str, str] = {}
    for key, values in parse_qs(parsed.query).items():
        if values:
            options[key] = values[0]

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(port) if port else "",
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": options,
        "ATOMIC_REQUESTS": False,
    }


def validate_redis_url(url: str, *, variable_name: str = "REDIS_URL") -> str:
    """Validate a Redis URL's shape. Celery and the cache accept the URL directly."""
    if not url or not url.strip():
        raise ConfigurationError(f"{variable_name} is required but missing or empty.")
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in ("redis", "rediss", "unix"):
        raise ConfigurationError(
            f"{variable_name} must use the redis://, rediss:// or unix:// scheme "
            "(received scheme not shown)."
        )
    if parsed.scheme.lower() != "unix" and not parsed.hostname:
        raise ConfigurationError(f"{variable_name} does not name a host.")
    return url.strip()


def validate_https_origin(value: str, *, variable_name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise ConfigurationError(f"{variable_name} must be an https:// origin.")
    if not parsed.hostname:
        raise ConfigurationError(f"{variable_name} does not name a host.")
    if "*" in value:
        raise ConfigurationError(f"{variable_name} must not contain a wildcard.")
    return value.rstrip("/")


def require_no_wildcard(values: list[str], *, variable_name: str) -> list[str]:
    if not values:
        raise ConfigurationError(f"{variable_name} is required but missing or empty.")
    for item in values:
        if "*" in item:
            raise ConfigurationError(
                f"{variable_name} must list explicit entries; wildcards are rejected."
            )
    return values


def validate_deployment_secret_key(value: str | None) -> str:
    """Reject an absent, short, or known-development secret key outside local/test."""
    if not value:
        raise ConfigurationError("DJANGO_SECRET_KEY is required but missing or empty.")
    if value in KNOWN_DEVELOPMENT_SECRET_KEYS:
        raise ConfigurationError(
            "DJANGO_SECRET_KEY is a known development default and is rejected here."
        )
    if value.startswith("django-insecure-"):
        raise ConfigurationError(
            "DJANGO_SECRET_KEY uses the insecure development prefix and is rejected here."
        )
    if len(value) < 50:
        raise ConfigurationError("DJANGO_SECRET_KEY is too short (minimum 50 characters).")
    return value


def validate_phase_boundaries(app_env: str) -> None:
    """Enforce the side-effect boundaries that hold through Phase 8.

    EXTERNAL_ACTIONS_ENABLED must be false and EVIDENCE_MODE must be metadata_only.
    Deployed environments reject a violation outright rather than warning.
    """
    external_actions = get_bool("EXTERNAL_ACTIONS_ENABLED", default=False)
    if external_actions:
        raise ConfigurationError(
            "EXTERNAL_ACTIONS_ENABLED is true. External side effects are forbidden "
            "through Phase 8; no provider adapter exists."
        )

    evidence_mode = get_choice(
        "EVIDENCE_MODE", ("metadata_only",), default="metadata_only", required=True
    )
    if evidence_mode != "metadata_only":  # pragma: no cover - get_choice already constrains
        raise ConfigurationError("EVIDENCE_MODE must be metadata_only through Phase 8.")

    if app_env == "pilot" and get_str("DEMO_AS_OF") is not None:
        raise ConfigurationError("DEMO_AS_OF is not permitted when APP_ENV is pilot.")
