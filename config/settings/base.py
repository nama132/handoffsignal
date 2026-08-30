"""Settings shared by every environment.

Environment-specific modules (local, test, production) import from here. No module
in this package reads a dotenv file: the application boots from explicit defaults in
local/test and from platform-supplied variables in demo/pilot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from config import env

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# --------------------------------------------------------------------- environment
APP_ENV = env.get_app_env()
IS_DEVELOPMENT_ENV = APP_ENV in env.DEVELOPMENT_ENVS

# Enforce the Phase 8 side-effect boundary in every environment.
env.validate_phase_boundaries(APP_ENV)

EXTERNAL_ACTIONS_ENABLED = False  # No adapter exists. Not configurable upward.
EVIDENCE_MODE = "metadata_only"
DEMO_MODE = env.get_bool("DEMO_MODE", default=APP_ENV in ("local", "demo"))

# --------------------------------------------------------------------- core
SECRET_KEY = env.get_str("DJANGO_SECRET_KEY", default="")
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.common",
    "apps.organizations",
    "apps.operations",
    "apps.ingestion",
    "apps.exceptions",
    "apps.recovery",
    "apps.audit",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise must sit immediately after SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "apps.common.middleware.RequestIDMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Must follow AuthenticationMiddleware: it resolves the tenant from request.user.
    "apps.organizations.context.ActiveOrganizationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.common.context_processors.demo_banner",
            ],
        },
    },
]

# --------------------------------------------------------------------- database
DATABASES = {"default": env.parse_database_url(env.get_str("DATABASE_URL", required=True) or "")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------- auth
AUTH_USER_MODEL = "organizations.User"
AUTHENTICATION_BACKENDS = ["apps.organizations.auth_backends.EmailBackend"]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "app:home"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------- i18n / time
LANGUAGE_CODE = "en-us"
# Instants are stored as timezone-aware UTC. Site-local rendering is a display
# concern handled per site, never by changing this value (section 18).
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------- static
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Django 5.2's STORAGES is NOT merged with defaults, so both keys are required.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# --------------------------------------------------------------------- celery
# Wired only. No business task exists in Phase 1.
REDIS_URL = env.validate_redis_url(env.get_str("REDIS_URL", required=True) or "")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = False
# Tasks can be redelivered; every task must be idempotent (section 19).
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 600
CELERY_TASK_SOFT_TIME_LIMIT = 540
CELERY_WORKER_SOFT_SHUTDOWN_TIMEOUT = 30
# Redis redelivers anything not acked within the visibility timeout. Keep retry
# backoffs well below this value.
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# --------------------------------------------------------------------- security
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # the template needs to read the token
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 60 * 60 * 8
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# --------------------------------------------------------------------- logging
LOG_LEVEL = env.get_choice(
    "LOG_LEVEL", ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"), default="INFO"
)

LOGGING: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "config.logging_utils.JSONFormatter"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        # Request bodies are never logged. django.request is kept at WARNING so
        # 4xx/5xx are visible without emitting request content.
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.db.backends": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
