"""Template context shared by every page."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest


def demo_banner(request: HttpRequest) -> dict[str, object]:
    """Expose the synthetic-data banner state (section 30.1)."""
    return {
        "demo_mode": getattr(settings, "DEMO_MODE", False),
        "app_env": getattr(settings, "APP_ENV", "local"),
    }
