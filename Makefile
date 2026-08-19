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

# --- database ---------------------------------------------------------------

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
test-integration: $(VENV) db-up ## Integration tests — needs Postgres
	$(PY) -m pytest -m integration

.PHONY: data-quality
data-quality: $(VENV) ## Run the rules against the fixture
	-$(PY) -m checks tests/fixtures/outlets_sample.csv \
	  --coverage tests/fixtures/coverage_sample.csv

.PHONY: feed
feed: $(VENV) ## Build the public feed from the fixture into dist/
	$(PY) -m feed tests/fixtures/outlets_sample.csv \
	  --coverage tests/fixtures/coverage_sample.csv --out dist/feed --allow-errors

.PHONY: check
check: lint test test-integration ## Everything CI runs

.PHONY: clean
clean: ## Remove build and cache artefacts
	rm -rf dist .pytest_cache .ruff_cache htmlcov .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
