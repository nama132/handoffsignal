"""Celery application.

Settings are read from Django's CELERY_-prefixed configuration. Section 19: tasks may
be redelivered and must be idempotent; every task in apps.exceptions.tasks is.
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("ops_recovery_v2")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(["apps.exceptions"])

# Cadence. Exactly one beat process may run; the database schedule lease is defence in
# depth against a second one (section 19).
app.conf.beat_schedule = {
    "sweep-dispatch-intents": {
        "task": "apps.exceptions.tasks.sweep_dispatch_intents",
        "schedule": 60.0,
    },
    "schedule-detectors": {
        "task": "apps.exceptions.tasks.schedule_detectors",
        "schedule": 3600.0,
    },
}
