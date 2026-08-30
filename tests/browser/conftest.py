"""Browser-test fixtures.

pytest-playwright's sync API runs each test inside a greenlet with an event loop
present on the thread. Django's ORM sees that loop and refuses synchronous queries
(`SynchronousOnlyOperation`) even though nothing here is actually async. The guard
exists to catch blocking queries inside async views; a Playwright test is neither, so
it is lifted for these tests only -- scoped, and undone at the end of the session.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from _pytest.monkeypatch import MonkeyPatch


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright() -> Iterator[None]:
    patch = MonkeyPatch()
    patch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "1")
    try:
        yield
    finally:
        patch.undo()
