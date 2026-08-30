"""Outbound-network blocker.

Section 33.1: "Block unmocked outbound network access in automated tests."

This lives in its own module rather than in conftest.py so that the exception class
has one identity. pytest imports conftest.py under a synthetic module name; importing
it a second time as `tests.conftest` would create a distinct NetworkAccessBlocked
class and `pytest.raises` would silently fail to match it.

Loopback is allowed so the disposable PostgreSQL and Redis containers stay reachable.
psycopg connects through libpq (C) and does not traverse Python's socket module.
"""

from __future__ import annotations

import socket

ALLOWED_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "", None})

_real_socket_connect = socket.socket.connect
_real_create_connection = socket.create_connection


class NetworkAccessBlocked(RuntimeError):
    """Raised when a test attempts an unmocked outbound connection."""


def _host_of(address: object) -> object:
    if isinstance(address, tuple) and address:
        return address[0]
    return None


def _guarded_connect(self, address):  # type: ignore[no-untyped-def]
    if _host_of(address) not in ALLOWED_HOSTS:
        raise NetworkAccessBlocked(
            "Outbound network access is blocked in tests. Mock the call instead."
        )
    return _real_socket_connect(self, address)


def _guarded_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
    if _host_of(address) not in ALLOWED_HOSTS:
        raise NetworkAccessBlocked(
            "Outbound network access is blocked in tests. Mock the call instead."
        )
    return _real_create_connection(address, *args, **kwargs)


def install() -> None:
    socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
    socket.create_connection = _guarded_create_connection  # type: ignore[assignment]


def uninstall() -> None:
    socket.socket.connect = _real_socket_connect  # type: ignore[method-assign]
    socket.create_connection = _real_create_connection  # type: ignore[assignment]
