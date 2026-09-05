# One-command local setup and the same checks CI runs.
#
#   make setup     first time: venv, deps, .env, database
#   make check     everything CI will run, before you push
#
.DEFAULT_GOAL := help
SHELL := /bin/bash
VENV  := .venv
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip

.PHONY: help
help: ## Show these targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk -F':.*?## ' '{printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'

# --- setup ------------------------------------------------------------------

.PHONY: setup
setup: $(VENV) .env node_modules db-up migrate seed ## Provision everything for a new checkout
	@echo
	@echo "Ready. 'make run' starts the admin, 'make check' runs what CI runs."
	@echo "First time? 'make superuser' to create a login."

$(VENV):
	python3 -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -r requirements-dev.txt

.env:
	cp .env.example .env
	@echo "wrote .env from .env.example"

node_modules: package.json
	npm install --silent
	@touch node_modules

.PHONY: hooks
hooks: $(VENV) ## Install the pre-commit hooks (optional; make check is the same gate)
	$(PIP) install --quiet -r requirements-dev.txt
	$(VENV)/bin/pre-commit install
	@echo "hooks installed — ruff, whitespace and the unit tests run on commit"

# --- database ---------------------------------------------------------------

# Where the tests connect, and who starts the server.
#
# CI provides Postgres as a service container and sets the standard PG*
# variables (lnic-contracts python-checks.yml). Those win where they are
# set, and no compose database is started -- `make test-integration`
# means the same thing on a laptop and on a runner, which is the point of
# calling make from CI at all.
ifdef PGHOST
DATABASE_URL ?= postgres://$(PGUSER):$(PGPASSWORD)@$(PGHOST):$(PGPORT)/$(PGDATABASE)
DB_READY :=
else
DATABASE_URL ?= postgres://directory:directory@localhost:5434/directory
DB_READY := db-up
endif
export DATABASE_URL


.PHONY: db-up
db-up: ## Start local Postgres and wait until it accepts connections
	docker compose up -d db
	@until docker compose exec -T db pg_isready -U directory -d directory >/dev/null 2>&1; do \
	  sleep 1; \
	done
	@echo "postgres ready on localhost:5434"

.PHONY: db-down
db-down: ## Stop Postgres, keeping data
	docker compose stop db

.PHONY: db-reset
db-reset: ## Destroy the database and start clean
	docker compose down -v
	$(MAKE) db-up

# --- django -----------------------------------------------------------------

.PHONY: migrate
migrate: $(VENV) db-up ## Apply database migrations
	$(PY) manage.py migrate

.PHONY: migrations
migrations: $(VENV) ## Generate migrations after a model change
	$(PY) manage.py makemigrations directory

.PHONY: seed
seed: $(VENV) ## Create the controlled vocabularies
	$(PY) manage.py seed_vocabularies

.PHONY: superuser
superuser: $(VENV) ## Create an admin login
	$(PY) manage.py createsuperuser

.PHONY: run
run: $(VENV) db-up ## Start the admin at http://localhost:8000/admin/
	$(PY) manage.py runserver

.PHONY: docker-build
docker-build: ## Build the deployment image
	docker build -t news-source-directory .

# --- checks -----------------------------------------------------------------

.PHONY: lint
lint: $(VENV) ## Lint and format check
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

.PHONY: fmt
fmt: $(VENV) ## Apply formatting and safe fixes
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

.PHONY: test
test: $(VENV) ## Unit tests — no database needed
	$(PY) -m pytest -m "not integration"

.PHONY: test-integration
test-integration: $(VENV) $(DB_READY) ## Integration tests — needs Postgres
# The migrations check and the coverage floor were in CI only. This
# target ran `pytest -m integration` and nothing else, so a developer
# could run it green and still fail CI on an uncommitted migration or on
# coverage -- the exact gap the shared pattern exists to close. Coverage
# is measured over the whole suite, as CI measured it, because the floor
# (pyproject fail_under) was set against that number.
	$(PY) manage.py makemigrations --check --dry-run
	$(PY) -m pytest --cov --cov-report=term --cov-report=xml

.PHONY: data-quality
data-quality: $(VENV) ## The rules still detect the fixture's known defects
# This used to be a bare run with a `-` prefix, so it reported whatever
# it found and could not fail. CI meanwhile asserted the opposite: the
# fixture MUST fail the rules, and four named rules must fire. The
# assertion is the check, so it lives here now and CI calls it.
	PYTHON=$(PY) scripts/ci/data-quality.sh

.PHONY: feed
feed: $(VENV) ## Build the public feed from the fixture into dist/
	$(PY) -m feed tests/fixtures/outlets_sample.csv \
	  --coverage tests/fixtures/coverage_sample.csv --out dist/feed --allow-errors

.PHONY: feed-check
feed-check: $(VENV) node_modules ## The feed leaks no admin columns and builds reproducibly
	PYTHON=$(PY) scripts/ci/feed.sh

.PHONY: pages
pages: ## The mockup stays servable and the docs' links resolve
	scripts/ci/pages.sh

.PHONY: image
image: ## Both image stages build, and the container answers with no database
	scripts/ci/image.sh

.PHONY: coverage
coverage: $(VENV) db-up ## Whole suite with a coverage report and the floor
	$(PY) -m pytest --cov --cov-report=term

.PHONY: e2e
e2e: node_modules ## Browser tests against the mockup and the committed feed
	npx playwright install --with-deps chromium
	npx playwright test

.PHONY: check
check: lint test test-integration data-quality feed-check pages ## Everything CI runs
# `image` is deliberately not here: it builds two docker images and runs
# a container, which is minutes rather than seconds. CI runs it as its
# own job; `make image` runs it on demand.

.PHONY: clean
clean: ## Remove build and cache artefacts
	rm -rf dist .pytest_cache .ruff_cache htmlcov .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
