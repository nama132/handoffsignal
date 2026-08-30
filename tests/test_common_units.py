"""Unit tests for the shared primitives: logging redaction, request IDs, auth
backend normalization, and the remaining environment-parsing branches."""

from __future__ import annotations

import logging
from unittest import mock

import pytest

from apps.common.middleware import REQUEST_ID_HEADER, RequestIDMiddleware
from config import env
from config.logging_utils import JSONFormatter


class TestJSONFormatter:
    def _record(self, **kwargs) -> logging.LogRecord:
        defaults = {
            "name": "test.logger",
            "level": logging.INFO,
            "pathname": "/x/y.py",
            "lineno": 10,
            "msg": "hello %s",
            "args": ("world",),
            "exc_info": None,
        }
        defaults.update(kwargs)
        return logging.LogRecord(**defaults)

    def test_emits_single_line_json(self) -> None:
        import json

        line = JSONFormatter().format(self._record())
        assert "\n" not in line
        payload = json.loads(line)
        assert payload["message"] == "hello world"
        assert payload["level"] == "INFO"
        assert payload["logger"] == "test.logger"

    def test_includes_request_id_when_present(self) -> None:
        import json

        record = self._record()
        record.request_id = "abc-123"
        assert json.loads(JSONFormatter().format(record))["request_id"] == "abc-123"

    def test_exception_type_only_never_the_traceback(self) -> None:
        import json

        try:
            raise ValueError("secret-token-in-message")
        except ValueError:
            import sys

            record = self._record(exc_info=sys.exc_info())
        payload = json.loads(JSONFormatter().format(record))
        assert payload["exc_type"] == "ValueError"
        assert "secret-token-in-message" not in json.dumps(payload)
        assert "Traceback" not in json.dumps(payload)

    def test_arbitrary_attributes_are_not_emitted(self) -> None:
        """Only allowlisted fields may reach the log stream."""
        import json

        record = self._record()
        record.password = "hunter2"  # noqa: S105
        record.request_body = {"ssn": "123-45-6789"}
        payload = json.dumps(json.loads(JSONFormatter().format(record)))
        assert "hunter2" not in payload
        assert "123-45-6789" not in payload


class TestRequestIDMiddleware:
    def _run(self, headers: dict[str, str]):
        from django.http import HttpResponse
        from django.test import RequestFactory

        request = RequestFactory().get("/", headers=headers)
        captured = {}

        def view(req):
            captured["request_id"] = req.request_id
            return HttpResponse("ok")

        response = RequestIDMiddleware(view)(request)
        return captured["request_id"], response

    def test_generates_an_id_when_absent(self) -> None:
        request_id, response = self._run({})
        assert request_id
        assert response[REQUEST_ID_HEADER] == request_id

    def test_accepts_a_safe_inbound_id(self) -> None:
        request_id, _ = self._run({"x-request-id": "abc123-def456"})
        assert request_id == "abc123-def456"

    @pytest.mark.parametrize(
        "value", ["../../etc/passwd", "<script>alert(1)</script>", "x" * 200, "a b c"]
    )
    def test_rejects_an_unsafe_inbound_id(self, value: str) -> None:
        """An untrusted header must not flow into logs verbatim."""
        request_id, _ = self._run({"x-request-id": value})
        assert request_id != value


@pytest.mark.django_db
class TestEmailBackend:
    def test_authenticates_with_differently_cased_email(self, user, user_password) -> None:
        from django.contrib.auth import authenticate

        assert authenticate(None, username=user.email.upper(), password=user_password) == user

    def test_returns_none_for_unknown_user(self) -> None:
        from django.contrib.auth import authenticate

        assert authenticate(None, username="nobody@example.test", password="x") is None

    def test_returns_none_when_identifier_is_missing(self) -> None:
        from apps.organizations.auth_backends import EmailBackend

        assert EmailBackend().authenticate(None, username=None, password="x") is None

    def test_returns_none_for_an_unnormalizable_identifier(self) -> None:
        from apps.organizations.auth_backends import EmailBackend

        with mock.patch(
            "apps.organizations.auth_backends.UserManager.normalize_login_email",
            side_effect=ValueError("bad"),
        ):
            assert EmailBackend().authenticate(None, username="  ", password="x") is None

    def test_wrong_password_is_rejected(self, user) -> None:
        from django.contrib.auth import authenticate

        assert authenticate(None, username=user.email, password="nope") is None


class TestEnvRemainingBranches:
    def test_get_str_returns_none_when_optional_and_absent(self, monkeypatch) -> None:
        monkeypatch.delenv("TOTALLY_ABSENT", raising=False)
        assert env.get_str("TOTALLY_ABSENT") is None

    def test_get_str_raises_when_required_with_no_default(self, monkeypatch) -> None:
        monkeypatch.delenv("TOTALLY_ABSENT", raising=False)
        with pytest.raises(env.ConfigurationError):
            env.get_str("TOTALLY_ABSENT", required=True)

    def test_get_str_default_satisfies_required(self, monkeypatch) -> None:
        monkeypatch.delenv("TOTALLY_ABSENT", raising=False)
        assert env.get_str("TOTALLY_ABSENT", "fallback", required=True) == "fallback"

    def test_get_str_treats_whitespace_as_empty(self, monkeypatch) -> None:
        monkeypatch.setenv("BLANKISH", "   ")
        assert env.get_str("BLANKISH", "fallback") == "fallback"

    def test_get_bool_without_default_or_requirement_raises(self, monkeypatch) -> None:
        monkeypatch.delenv("TOTALLY_ABSENT", raising=False)
        with pytest.raises(env.ConfigurationError):
            env.get_bool("TOTALLY_ABSENT")

    def test_get_bool_required_and_absent_raises(self, monkeypatch) -> None:
        monkeypatch.delenv("TOTALLY_ABSENT", raising=False)
        with pytest.raises(env.ConfigurationError):
            env.get_bool("TOTALLY_ABSENT", required=True)

    def test_get_choice_rejects_absent_required_value(self, monkeypatch) -> None:
        monkeypatch.delenv("TOTALLY_ABSENT", raising=False)
        with pytest.raises(env.ConfigurationError):
            env.get_choice("TOTALLY_ABSENT", ("a", "b"))

    def test_get_csv_list_parses_and_trims(self, monkeypatch) -> None:
        monkeypatch.setenv("HOSTS", " a.example.com , b.example.com ,, ")
        assert env.get_csv_list("HOSTS") == ["a.example.com", "b.example.com"]

    def test_get_csv_list_empty_when_optional_and_absent(self, monkeypatch) -> None:
        monkeypatch.delenv("HOSTS", raising=False)
        assert env.get_csv_list("HOSTS") == []

    def test_get_csv_list_required_and_absent_raises(self, monkeypatch) -> None:
        monkeypatch.delenv("HOSTS", raising=False)
        with pytest.raises(env.ConfigurationError):
            env.get_csv_list("HOSTS", required=True)

    def test_unix_socket_redis_url_is_accepted(self) -> None:
        assert env.validate_redis_url("unix:///var/run/redis.sock")

    def test_database_url_without_port_is_accepted(self) -> None:
        config = env.parse_database_url("postgresql://u:p@localhost/opsrecovery_v2")
        assert config["PORT"] == ""

    def test_database_url_with_invalid_port_is_rejected(self) -> None:
        with pytest.raises(env.ConfigurationError):
            env.parse_database_url("postgresql://u:p@localhost:notaport/db")

    def test_https_origin_without_host_is_rejected(self) -> None:
        with pytest.raises(env.ConfigurationError):
            env.validate_https_origin("https://", variable_name="APP_BASE_URL")
