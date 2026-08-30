"""Deployed settings for the demo and pilot environments.

Every relaxation available in local/test is rejected here: debug mode, wildcard
hosts, SQLite, and known development secrets all fail startup rather than degrade.
Validation reports variable NAMES only, never values (section 20.1).
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "demo")

from config import env  # noqa: E402

from .base import *  # noqa: E402,F401,F403

if APP_ENV not in ("demo", "pilot"):  # noqa: F405
    raise env.ConfigurationError("Production settings require APP_ENV to be demo or pilot.")

# --------------------------------------------------------------------- hard refusals
DEBUG = False
if env.get_bool("DJANGO_DEBUG", default=False):
    raise env.ConfigurationError("DJANGO_DEBUG must not be enabled in a deployed environment.")

SECRET_KEY = env.validate_deployment_secret_key(env.get_str("DJANGO_SECRET_KEY"))

ALLOWED_HOSTS = env.require_no_wildcard(
    env.get_csv_list("DJANGO_ALLOWED_HOSTS", required=True),
    variable_name="DJANGO_ALLOWED_HOSTS",
)

CSRF_TRUSTED_ORIGINS = [
    env.validate_https_origin(origin, variable_name="DJANGO_CSRF_TRUSTED_ORIGINS")
    for origin in env.require_no_wildcard(
        env.get_csv_list("DJANGO_CSRF_TRUSTED_ORIGINS", required=True),
        variable_name="DJANGO_CSRF_TRUSTED_ORIGINS",
    )
]

APP_BASE_URL = env.validate_https_origin(
    env.get_str("APP_BASE_URL", required=True) or "", variable_name="APP_BASE_URL"
)

# --------------------------------------------------------------------- transport
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# HSTS is enabled only once HTTPS is verified for the deployed domain.
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = False

# --------------------------------------------------------------------- static
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
WHITENOISE_MAX_AGE = 31536000

# --------------------------------------------------------------------- demo controls
# No public signup, seed, or reset endpoint may exist in a deployed environment.
ALLOW_PUBLIC_DEMO_RESET = False
