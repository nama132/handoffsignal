"""Shared test fixtures.

The outbound-network blocker lives in tests/network_guard.py so its exception class
has a single identity regardless of how pytest imports this file.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests import network_guard


@pytest.fixture(scope="session", autouse=True)
def _block_outbound_network() -> Iterator[None]:
    network_guard.install()
    try:
        yield
    finally:
        network_guard.uninstall()


@pytest.fixture
def user_password() -> str:
    return "correct-horse-battery-staple"


@pytest.fixture
def user(db, user_password):  # type: ignore[no-untyped-def]
    from apps.organizations.models import User

    return User.objects.create_user(
        email="Operations.Manager@example.test",
        password=user_password,
        display_name="Operations Manager",
    )
