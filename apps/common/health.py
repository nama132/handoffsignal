"""Health endpoints.

Section 19: "Readiness checks cover database and required queue connectivity.
Liveness does not perform external calls."
Section 20: responses must not reveal connection details.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import connections
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)

_REDIS_SOCKET_TIMEOUT_SECONDS = 2.0
_DATABASE_STATEMENT_TIMEOUT_MS = 2000


@require_GET
@never_cache
def liveness(request: HttpRequest) -> JsonResponse:
    """Cheap process check. Performs no database, cache, or network work."""
    return JsonResponse({"status": "ok"}, status=200)


def _check_database() -> bool:
    try:
        connection = connections["default"]
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = %s", [_DATABASE_STATEMENT_TIMEOUT_MS])
            cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)
    except Exception:
        # Logged without the exception message: it can contain host/credential detail.
        logger.warning("readiness: database check failed")
        return False


def _check_redis() -> bool:
    try:
        import redis  # provided by celery[redis]

        client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
            socket_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
        )
        try:
            return bool(client.ping())
        finally:
            client.close()
    except Exception:
        logger.warning("readiness: redis check failed")
        return False


@require_GET
@never_cache
def readiness(request: HttpRequest) -> JsonResponse:
    """Database and queue readiness. Returns 200 only when both are usable."""
    checks = {"database": _check_database(), "redis": _check_redis()}
    healthy = all(checks.values())
    # Boolean per dependency only — no host, port, driver, or error text.
    return JsonResponse(
        {"status": "ready" if healthy else "not_ready", "checks": checks},
        status=200 if healthy else 503,
    )
