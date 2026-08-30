# OpsRecovery V2 — convenience targets. Underlying commands are documented in
# docs/runbooks/local-development.md so nothing is hidden behind a wrapper.

SHELL := /bin/bash
.DEFAULT_GOAL := help

TEST_SETTINGS := config.settings.test
LOCAL_SETTINGS := config.settings.local

.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-26s\033[0m %s\n", $$1, $$2}'

# ----------------------------------------------------------------- environment
.PHONY: install
install: ## Sync the locked environment (all dependency groups)
	uv sync --frozen --all-groups

.PHONY: lock
lock: ## Re-resolve dependencies after editing pyproject.toml
	uv lock

.PHONY: up
up: ## Start local PostgreSQL and Redis
	docker compose up -d db redis

.PHONY: down
down: ## Stop local services (volumes are preserved)
	docker compose down

.PHONY: logs
logs: ## Tail local service logs
	docker compose logs -f db redis

# ----------------------------------------------------------------- django
.PHONY: migrate
migrate: ## Apply migrations to the local database
	uv run python manage.py migrate

.PHONY: check
check: ## Run Django system checks
	uv run python manage.py check
	uv run python manage.py makemigrations --check --dry-run

.PHONY: run
run: ## Start the development server
	uv run python manage.py runserver

.PHONY: worker
worker: ## Start a Celery worker (manual development only)
	uv run celery -A config worker --loglevel=INFO

.PHONY: beat
beat: ## Start the Celery beat scheduler (exactly one instance)
	uv run celery -A config beat --loglevel=INFO

.PHONY: demo-reset
demo-reset: ## Wipe and reload the whole synthetic demo story, ready to rehearse
	uv run python manage.py seed_demo --reset
	uv run python manage.py demo_load

.PHONY: demo
demo: demo-reset run ## Reload the demo story and start the server

.PHONY: createowner
createowner: ## Create a platform superuser locally
	uv run python manage.py createsuperuser

# ----------------------------------------------------------------- quality
.PHONY: fmt
fmt: ## Format and fix imports
	uv run ruff check --select I --fix .
	uv run ruff format .

.PHONY: lint
lint: ## Formatting, lint, and type checks
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy apps config

.PHONY: test
test: ## Run the test suite (excludes worker_integration; browser tests skip without Chromium)
	uv run pytest -q -m "not worker_integration"

.PHONY: browser-install
browser-install: ## Install the pinned Chromium used by the Route B journey tests
	uv run playwright install chromium

.PHONY: test-browser
test-browser: ## Run the Route B Playwright controls (needs `make browser-install` once)
	uv run pytest -q -m browser

.PHONY: coverage
coverage: ## Run tests under coverage and enforce the floor
	uv run coverage run -m pytest -m "not worker_integration"
	uv run coverage report --fail-under=85

.PHONY: audit
audit: ## Dependency vulnerability audit
	uv export --no-emit-project --no-hashes --format requirements.txt -o requirements-audit.txt --quiet
	uv run pip-audit -r requirements-audit.txt

.PHONY: qa
qa: check lint test ## Everything a phase gate requires, except coverage and audit

# ----------------------------------------------------------------- worker tests
# Owns the worker lifecycle: isolated queue, bounded readiness wait, guaranteed
# cleanup via trap. Never relies on a developer running a foreground worker.
# No business task exists in Phase 1, so this target reports and exits cleanly.
.PHONY: test-worker-integration
test-worker-integration: ## Run worker_integration tests against a real Celery worker
	@set -euo pipefail; \
	if [ "$${APP_ENV:-test}" != "test" ]; then \
		echo "refusing to run: APP_ENV must be 'test'"; exit 1; fi; \
	QUEUE="v2_test_worker_$$$$"; \
	WORKER_PID=""; \
	cleanup() { if [ -n "$$WORKER_PID" ]; then kill "$$WORKER_PID" 2>/dev/null || true; \
		wait "$$WORKER_PID" 2>/dev/null || true; fi; }; \
	trap cleanup EXIT INT TERM; \
	if ! uv run pytest --collect-only -q -m worker_integration 2>/dev/null | grep -q "test"; then \
		echo "no worker_integration tests are registered yet (expected in Phase 1)"; exit 0; fi; \
	DJANGO_SETTINGS_MODULE=$(TEST_SETTINGS) uv run celery -A config worker \
		--queues "$$QUEUE" --concurrency 1 --loglevel=WARNING & WORKER_PID=$$!; \
	for i in $$(seq 1 30); do \
		if DJANGO_SETTINGS_MODULE=$(TEST_SETTINGS) uv run celery -A config inspect ping \
			--destination "celery@$$(hostname)" >/dev/null 2>&1; then break; fi; \
		if [ "$$i" = "30" ]; then echo "worker did not become ready within timeout"; exit 1; fi; \
		sleep 1; \
	done; \
	V2_TEST_QUEUE="$$QUEUE" uv run pytest -q -m worker_integration
