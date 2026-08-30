"""Local development settings.

Explicit development defaults are set here so the application boots and tests run
without a .env file (Phase 1 implementation rule). These values are recognised by
production validation as insecure and are rejected there.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault(
    "DJANGO_SECRET_KEY", "django-insecure-local-development-key-not-for-deployment"
)
os.environ.setdefault(
    "DATABASE_URL", "postgresql://opsrecovery:local-dev-only@127.0.0.1:5433/opsrecovery_v2"
)
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6380/0")

from .base import *  # noqa: E402,F401,F403

DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
INTERNAL_IPS = ["127.0.0.1"]

# Cookies are not marked Secure locally because development runs over plain HTTP.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
