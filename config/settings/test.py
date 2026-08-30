"""Test settings.

Master prompt section 33.1:
  - disposable PostgreSQL only, never SQLite, never a URL inherited from V1;
  - ignore root dotenv files and construct an explicit test configuration;
  - refuse a database name/host outside an allowlisted local/CI test pattern;
  - block unmocked outbound network access;
  - fail if external actions are enabled.

No dotenv loader is imported anywhere in this project, so a root .env cannot leak in.
The DATABASE_URL below is set with os.environ[...] (not setdefault) so an inherited
value cannot silently redirect the test run.
"""

from __future__ import annotations

import os

os.environ["APP_ENV"] = "test"
os.environ["EXTERNAL_ACTIONS_ENABLED"] = "false"
os.environ["EVIDENCE_MODE"] = "metadata_only"
os.environ["DEMO_MODE"] = "false"
os.environ.setdefault(
    "DJANGO_SECRET_KEY", "django-insecure-local-development-key-not-for-deployment"
)
# Explicitly constructed; never inherited.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://opsrecovery:local-dev-only@127.0.0.1:5433/opsrecovery_v2_test",
)
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6380/1")

from config.dbguard import assert_test_database  # noqa: E402

from .base import *  # noqa: E402,F401,F403

# Refuse a non-test database target before anything can connect to it.
assert_test_database(DATABASES["default"]["NAME"], DATABASES["default"]["HOST"])  # noqa: F405

DEBUG = False
ALLOWED_HOSTS = ["testserver", "127.0.0.1", "localhost"]

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

# Fast, deterministic hashing for tests only.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Celery unit tests run eagerly; worker_integration tests use a real worker.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

LOGGING["root"]["level"] = "CRITICAL"  # noqa: F405
