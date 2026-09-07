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
# set, and no compose database is started -- `make test` means the same
# thing on a laptop and on a runner, which is the point of calling make
# from CI at all.
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
test: $(VENV) $(DB_READY) ## The whole suite on Postgres, then the suite's coverage floor
# One target, the whole suite. It used to be two: `test` ran the unit
# tests without a database and `test-integration` ran everything with
# coverage, so the number the floor judged came from the second and a
# green `make test` said nothing about it. Coverage is over the whole
# suite because that is what the floor was set against, and the floor
# is lnic-contracts' -- one number for every repository in the suite,
# read from coverage.xml. The unit subset is still `pytest -m "not
# integration"` for a quick loop before Docker is up.
	$(PY) manage.py makemigrations --check --dry-run
	$(PY) -m pytest --cov --cov-report=term --cov-report=xml
	$(PY) -m lnic_contracts.coverage_floor coverage.xml

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

.PHONY: e2e
e2e: node_modules ## Browser tests against the mockup and the committed feed
	npx playwright install --with-deps chromium
	npx playwright test

.PHONY: check
check: lint test data-quality feed-check pages ## Everything CI runs
# `image` is deliberately not here: it builds two docker images and runs
# a container, which is minutes rather than seconds. CI runs it as its
# own job; `make image` runs it on demand.

.PHONY: clean
clean: ## Remove build and cache artefacts
	rm -rf dist .pytest_cache .ruff_cache htmlcov .coverage coverage.xml
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
