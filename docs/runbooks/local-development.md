# Runbook — local development

Every command runs from the workspace root:
`/Users/amanabbas/Desktop/Project AI/V2/ops-recovery-v2`

## First-time setup

```bash
brew install uv                 # or the standalone installer from docs.astral.sh/uv
uv python install 3.13          # managed CPython 3.13.15; system Python is untouched
uv sync --frozen --all-groups
docker compose up -d db redis
uv run python manage.py migrate
uv run python manage.py createsuperuser
```

## Daily commands

| Task | Command | Make target |
|---|---|---|
| Start services | `docker compose up -d db redis` | `make up` |
| Stop services | `docker compose down` | `make down` |
| Run the server | `uv run python manage.py runserver` | `make run` |
| Apply migrations | `uv run python manage.py migrate` | `make migrate` |
| Django checks + drift | `uv run python manage.py check && uv run python manage.py makemigrations --check --dry-run` | `make check` |
| Format and sort imports | `uv run ruff check --select I --fix . && uv run ruff format .` | `make fmt` |
| Lint and type-check | `uv run ruff format --check . && uv run ruff check . && uv run mypy apps config` | `make lint` |
| Tests | `uv run pytest -q -m "not worker_integration"` | `make test` |
| Coverage | `uv run coverage run -m pytest -m "not worker_integration" && uv run coverage report --fail-under=85` | `make coverage` |
| Dependency audit | `uv export --no-emit-project --no-hashes --format requirements.txt -o requirements-audit.txt && uv run pip-audit -r requirements-audit.txt` | `make audit` |
| Worker (manual) | `uv run celery -A config worker --loglevel=INFO` | `make worker` |
| Beat (exactly one) | `uv run celery -A config beat --loglevel=INFO` | `make beat` |

`make qa` runs checks, lint, and tests together.

## Local service details

| Service | Image | Host port | Notes |
|---|---|---|---|
| PostgreSQL | `postgres:18.6-trixie` | 5433 | Volume mounted at `/var/lib/postgresql` (the PG18 path) |
| Redis | `redis:8.10-alpine` | 6380 | `maxmemory-policy noeviction` for Celery correctness |

Ports are deliberately non-default so this stack cannot collide with any other
local PostgreSQL or Redis. Credentials are local-development-only.

## Adding or changing a dependency

```bash
# edit pyproject.toml, then:
uv lock                       # re-resolve
git diff uv.lock              # REVIEW the diff before continuing
uv sync --frozen --all-groups
```

Do not pin `redis-py` directly. `kombu` 5.6.2 constrains it to `<6.5`, so
`celery[redis]` resolves 6.4.0; an explicit `redis>=7` pin makes the resolution
unsolvable. See ADR 0004.

## Troubleshooting

**`ConfigurationError: <NAME> is required but missing or empty`**
Startup validation is working as designed. It names the variable and never prints
its value. Compare against `.env.example`.

**`Refusing to run tests: ...test pattern`**
`config/dbguard.py` blocked a test run against a database that does not look
disposable. Check `TEST_DATABASE_URL`; do not weaken the guard.

**`NetworkAccessBlocked` in a test**
A test attempted a real outbound connection. Mock it. Loopback is allowed so the
containers stay reachable.

**`connection refused` on migrate**
`docker compose ps` — the database reports `healthy` only after initialisation.

**Docker daemon not running**
`open -a Docker` on macOS, then wait for `docker info` to succeed.

## What must never be run

```bash
docker compose down -v      # deletes the local V2 database volume
```

Never run V1's tests or application. Several V1 modules call
`load_dotenv(override=True)` and its verification scripts can seed or mutate the
configured database; a local environment may hold live provider settings.

## Not yet available

`make test-worker-integration` exits immediately with a message: no Celery business
task exists in Phase 1. It becomes meaningful in Phase 4.
