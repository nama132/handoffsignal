# OpsRecovery V2 application image.
#
# One image serves the web, worker, and beat roles; the command differs per service.
# The base suite is pinned explicitly: python:3.13-slim now resolves to Debian
# trixie, and an unpinned suite would change libpq/OpenSSL under psycopg silently.

FROM python:3.13.15-slim-trixie AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# uv is copied from its official distroless image and pinned by tag.
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/

WORKDIR /app

# Dependency layer: cached until the lock file changes.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
RUN uv sync --locked --no-dev

# Static assets are collected at BUILD time. Railway's pre-deploy command runs in a
# separate container, so filesystem changes made there would not reach the runtime.
RUN APP_ENV=local DJANGO_SETTINGS_MODULE=config.settings.local \
    uv run python manage.py collectstatic --noinput

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Overridden per service. Web binds the platform-injected PORT; worker and beat
# ignore it and receive no public domain.
CMD ["/bin/sh", "-c", "exec uv run gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000}"]
