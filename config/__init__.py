"""Project configuration package.

The Celery application is imported here so `celery -A config` resolves it and so a
shared_task registered in a later phase binds to the right app.
"""

from __future__ import annotations

from config.celery import app as celery_app

__all__ = ("celery_app",)
