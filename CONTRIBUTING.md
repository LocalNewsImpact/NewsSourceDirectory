# Contributing

## Getting a local environment

### Prerequisites

| | Version | Why |
|---|---|---|
| Python | 3.11 or later | `requires-python = ">=3.11"` in `pyproject.toml` |
| Docker | any current release | runs Postgres 16; nothing else needs it |
| Node | 22 | matches the version CI pins; the only package is `minisearch`, used to build the search index |

No GCP access, no credentials and no network data source are required. The whole
project runs locally against the fixtures in `tests/fixtures/`.

```bash
python3 --version && docker --version && node --version
```

### Setup

```bash
git clone https://github.com/LocalNewsImpact/NewsSourceDirectory.git
cd NewsSourceDirectory
make setup
```

`make setup` creates the virtualenv, installs Python and Node dependencies,
writes `.env` from `.env.example`, starts Postgres in Docker on port 5434,
applies the migrations, and seeds the controlled vocabularies. It takes about
90 seconds on a first run and is safe to rerun — each step is skipped if it is
already done.

Seeding the vocabularies is not optional dressing. Empty dropdowns are how the
source data acquired "Public Broadcasting" beside "Public Broadcast".

It has finished when it prints:

```
Ready. 'make run' starts the admin, 'make check' runs what CI runs.
```

### Confirm the checkout works

```bash
make check
```

Expect lint clean, then **163 unit tests** and **118 integration tests** passing,
in roughly 15 seconds. Anything less means the environment is wrong rather than
the code.

### Run it

```bash
make superuser   # once, to create a login
make run         # http://localhost:8000/admin/
```

Sign-in falls back to a normal Django login: `.env.example` leaves
`GOOGLE_OAUTH_CLIENT_ID` blank, so no OAuth credentials are needed to work on the
admin. Google sign-in is used in deployed environments only.

### Getting data into it

A fresh database has the vocabularies and nothing else. The admin is empty until
something is imported.

```bash
# the committed sample — small, fast, enough to exercise the admin
.venv/bin/python manage.py import_source tests/fixtures/coverage_sample.csv
.venv/bin/python manage.py rebuild_outlets
```

`import_source` accepts a path or an https URL, `.csv` or `.xlsx`, and takes
`--dry-run` and `--limit`. It writes `CoverageRecord` rows and nothing else;
`rebuild_outlets` is what derives `Outlet` from them. Running the two in that
order is the whole import path, and it is how production is loaded as well.

Places are separate and optional locally. `seed_places` reads the GNIS national
file, which is large; `--states Missouri` keeps it manageable, and `--url`
downloads the file rather than requiring a local copy.

### Optional: commit hooks

`.pre-commit-config.yaml` runs ruff, whitespace fixes and the unit tests before
each commit. `make setup` does not install it, because a hook that surprises
someone mid-commit is worse than a check they chose:

```bash
make hooks
```

It catches the same things `make check` does, earlier. Skipping it costs nothing
so long as `make check` passes before you push.

### Ports

Postgres is published on **5434**, deliberately: 5432 is usually a system
Postgres and 5433 belongs to the crawler's test container, so a checkout of this
project will not collide with either.

The port appears in `docker-compose.yml` and in `DATABASE_URL` in `.env`. Change
both together if 5434 is taken on your machine.

**Two checkouts share one database.** The container is pinned to
`container_name: nsd-postgres` and Compose derives its project name from the
directory, so a second clone in a directory of the same name attaches to the
running container and its volume rather than creating its own. Nothing warns you.
An import run from one checkout appears in the other, and `make db-reset` in
either destroys both. Give the second clone a different directory name, or a
different `container_name` and port, if the two need separate data.

### When something fails

| Symptom | Cause |
|---|---|
| `make setup` hangs at `db-up` | Docker is not running. The wait loop has no timeout and will sit there. |
| `Bind for 0.0.0.0:5434 failed` | Something already holds the port — often another checkout of this project. `docker ps` will name it. |
| `connection refused` on 5434 | The container is stopped. `make db-up`. |
| Integration tests fail, unit tests pass | Postgres is unreachable, not a code fault. The split exists so `make test` stays green before Docker is working. |
| Migrations conflict after switching branches | `make db-reset` destroys the volume and rebuilds. Local data is not precious. |

`make db-down` stops Postgres and keeps the data. `make db-reset` deletes it.
`make clean` removes build and cache artefacts and touches nothing else.

## Tests

**Unit** tests need nothing but the virtualenv. They cover the data-quality
rules, the identity rule, the feed builder, and the mockup's structure.

**Integration** tests are marked `@pytest.mark.integration` and need Postgres:

```bash
make test          # unit only
make test-integration
make check         # lint, format check, and both suites — what CI runs
```

CI runs both on every branch, not only on pull requests.

## The workflow

```
branch  ->  push  ->  CI on every push  ->  PR  ->  review  ->  merge  ->  deploy
```

1. **Branch from `main`.** Nobody pushes to `main` directly; branch protection
   refuses it.
2. **Push early.** CI runs on every branch, not only on pull requests, so you see
   failures before opening a PR.
3. **Open a pull request.** The template asks what changed, why, and how you
   verified it.
4. **CI must pass.** Lint, unit, integration, data quality, feed build, and the
   Pages payload check are all required.
5. **A reviewer must approve.** Approval is required after checks pass. Pushing
   a new commit dismisses stale approvals.
6. **Merge.** That triggers deployment.

### What `main` actually enforces

Set on the branch, not by convention:

| Rule | Setting |
|---|---|
| Direct pushes | blocked — pull request required |
| Approvals | 1, from a CODEOWNER |
| Stale approvals | dismissed when you push again |
| Required checks | Lint, Tests, Integration, Data quality, Public feed, Pages payload |
| Branch must be current with `main` | yes |
| Unresolved conversations | block merge |
| Force push / delete `main` | blocked |

Administrators are currently exempt from the pull-request requirement, so that a
one-person day is not deadlocked by needing someone else to approve. Everyone
else is not. If the team grows past the point where that helps, turn it on with
`enforce_admins`.

### Tool versions are pinned exactly

`ruff` and `pytest` are pinned in `requirements-dev.txt`, and CI reads the pins
from that file rather than repeating them. This is not fussiness: a newer ruff
locally than in CI means "passes on my machine, fails in CI", and that is
precisely how an `F811` that shadowed `Outlet.identity_key` reached `main`.

Upgrade by changing the pin in one place, in its own pull request.

### Things that will fail review

- **Adding a column to the public feed without saying so.** `PUBLIC_FIELDS` and
  `COVERAGE_PUBLIC_FIELDS` are allowlists on purpose: a new field is private
  until someone decides otherwise. Widening one is a deliberate act, and the PR
  template asks you to flag it.
- **Loosening a data-quality rule to make CI green.** The fixture in
  `tests/fixtures/` is real prototype data and is *expected* to fail; the job
  asserts that each rule still fires. If a rule is wrong, fix the rule and say
  why in the PR — do not quiet it.
- **Committing `.env`, credentials, or `dist/`.** All are gitignored.

## Publishing the feed

The registry lives in a database, which produces no git event, so publishing is
triggered rather than inferred:

| Trigger | When |
|---|---|
| **"Publish the public feed now"** in the admin | an editor decides something is worth showing |
| after a successful **Deploy** | a projection or schema change alters the feed even with no edits |
| daily at 06:00 Central | the safety net beneath both |
| Actions → Run workflow | by hand |

The admin only *requests* a publish. The workflow does the reading, through a
role holding `SELECT` and nothing else, so the path that produces public data
cannot also change it.

The button needs a GitHub token with `contents: write` in the
`github-dispatch-token` secret. Without it the action says so plainly rather
than silently doing nothing.

## Running something against production

```bash
./infra/manage.sh ensure_admin matt@localnewsimpact.org someone@localnewsimpact.org
./infra/manage.sh rebuild_outlets
./infra/manage.sh seed_places --url --link
```

It runs the command inside Cloud Run **using the image currently serving**, so
the code is exactly what production is running and nothing needs installing
locally. Your machine never connects to the database; only your gcloud
credentials are used, and the database has no public route to reach anyway.

Expect roughly three minutes — most of it is Cloud Run creating the job and
starting a container. The command's own output is printed at the end.

Two things it handles that are easy to get wrong by hand: Cloud Run splits
arguments on commas, which breaks on URLs, and it bakes them into the job
definition rather than accepting them at execution time, so the job has to be
redeployed for each different command.

## Where things are

| Path | What |
|---|---|
| `checks/` | data-quality rules, run in CI and by `publish` |
| `feed/` | the public static feed builder |
| `directory/` | the Django app — models, admin, auth, identity rule |
| `config/` | settings and the two URLconfs, one per front end |
| `infra/` | `bootstrap.sh` — the GCP project, idempotent |
| `mockup/` | the working UI prototype, served on GitHub Pages |
| `docs/` | auth design, schema decisions |

Start with `README.md` for the architecture and `MIGRATION.md` for why the data
needs the work it needs.
