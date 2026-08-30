"""Health endpoint behaviour (section 19)."""

from __future__ import annotations

from unittest import mock

import pytest
from django.urls import reverse


def test_liveness_returns_ok_without_touching_the_database(client) -> None:
    """Liveness must not perform database, cache, or network work."""
    with (
        mock.patch("apps.common.health._check_database") as db_check,
        mock.patch("apps.common.health._check_redis") as redis_check,
    ):
        response = client.get(reverse("health-live"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    db_check.assert_not_called()
    redis_check.assert_not_called()


def test_liveness_requires_no_authentication(client) -> None:
    assert client.get(reverse("health-live")).status_code == 200


@pytest.mark.django_db
def test_readiness_succeeds_when_dependencies_are_available(client) -> None:
    with mock.patch("apps.common.health._check_redis", return_value=True):
        response = client.get(reverse("health-ready"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["checks"] == {"database": True, "redis": True}


def test_readiness_fails_safely_when_database_is_unavailable(client) -> None:
    with (
        mock.patch("apps.common.health._check_database", return_value=False),
        mock.patch("apps.common.health._check_redis", return_value=True),
    ):
        response = client.get(reverse("health-ready"))
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["database"] is False


def test_readiness_fails_safely_when_redis_is_unavailable(client) -> None:
    with (
        mock.patch("apps.common.health._check_database", return_value=True),
        mock.patch("apps.common.health._check_redis", return_value=False),
    ):
        response = client.get(reverse("health-ready"))
    assert response.status_code == 503
    assert response.json()["checks"]["redis"] is False


def test_readiness_response_reveals_no_connection_details(client) -> None:
    """The payload must be booleans only: no host, port, driver, or error text."""
    with (
        mock.patch("apps.common.health._check_database", return_value=False),
        mock.patch("apps.common.health._check_redis", return_value=False),
    ):
        response = client.get(reverse("health-ready"))
    body = response.content.decode()
    for leak in ("127.0.0.1", "5433", "6380", "password", "opsrecovery", "postgresql"):
        assert leak not in body
    assert set(response.json()["checks"]) == {"database", "redis"}


def test_database_check_returns_false_on_error() -> None:
    from apps.common import health

    with mock.patch("apps.common.health.connections") as connections:
        connections.__getitem__.side_effect = RuntimeError("boom")
        assert health._check_database() is False


def test_redis_check_returns_false_on_error(settings) -> None:
    from apps.common import health

    settings.REDIS_URL = "redis://127.0.0.1:1/0"
    with mock.patch("redis.Redis.from_url", side_effect=RuntimeError("boom")):
        assert health._check_redis() is False


def test_health_endpoints_reject_post(client) -> None:
    assert client.post(reverse("health-live")).status_code == 405
    assert client.post(reverse("health-ready")).status_code == 405
