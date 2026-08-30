"""Shared guards for local-only management commands.

Section 31: the seed command must carry "a prominent guard that refuses outside
local/demo settings", must be idempotent, and must never be wired to a public route.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import CommandError

LOCAL_ENVIRONMENTS = ("local", "test", "demo")


def refuse_outside_local_or_demo(command_name: str) -> None:
    app_env = getattr(settings, "APP_ENV", None)
    if app_env not in LOCAL_ENVIRONMENTS:
        raise CommandError(
            f"{command_name} refuses to run with APP_ENV={app_env!r}. "
            f"It is permitted only in {list(LOCAL_ENVIRONMENTS)}."
        )
