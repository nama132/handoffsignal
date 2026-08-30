"""Proves the outbound-network blocker actually blocks."""

from __future__ import annotations

import socket

import pytest

from tests.network_guard import NetworkAccessBlocked


def test_outbound_socket_connect_is_blocked() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkAccessBlocked):
            sock.connect(("example.com", 80))
    finally:
        sock.close()


def test_outbound_create_connection_is_blocked() -> None:
    with pytest.raises(NetworkAccessBlocked):
        socket.create_connection(("example.com", 80), timeout=1)


def test_outbound_connection_by_ip_is_blocked() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkAccessBlocked):
            sock.connect(("93.184.216.34", 80))
    finally:
        sock.close()


def test_loopback_is_still_permitted() -> None:
    """Loopback must remain reachable so the disposable containers work."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect(("127.0.0.1", port))  # must not raise
    finally:
        client.close()
        server.close()
