# From a local edit to production

Three gates, each catching something the next one cannot afford to discover.
Nothing here is aspirational — every check described is in
`.github/workflows/` today.

```
local            make check
  ↓ push (any branch)
GitHub CI        7 jobs, on every push, not only pull requests
  ↓ merge to main (pull request + 1 approval required)
Deploy           build → migrate → shift traffic → prove it is reachable
  ↓
Publish feed     static payload to gh-pages
```

---

## 1. Local

```bash
make check     # exactly what CI runs: lint, format, unit, integration
```

Tests are split by marker rather than by directory:

| | Needs | Why the split |
|---|---|---|
| Unit — 163 | the virtualenv | A new contributor gets a green run before Docker works |
| Integration — 118 | Postgres on 5434 | Real database behaviour, not a mock of it |

`make test` runs the first; `make test-integration` runs the second and starts
the container for you. `make hooks` optionally runs lint and the unit tests on
every commit.

The local Postgres is a container on port **5434** — chosen because 5432 is
usually a system Postgres and 5433 belongs to the crawler's test container. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for the trap where two checkouts share one
database.

## 2. GitHub CI

Runs on **every push to every branch**, and on pull requests. Failures surface
before a pull request exists rather than after review starts.

| Job | What it is actually protecting against |
|---|---|
| **Lint** | formatting drift; `ruff check` and `ruff format --check` against the pinned version |
| **Tests** | 163 unit tests over the rules, the identity key, the feed builder and the mockup |
| **Integration** | 118 tests against a real Postgres 16 service — **and `makemigrations --check`**, so a model change cannot merge without its migration |
| **Data quality** | the rules still detect known defects (see below) |
| **Public feed** | an admin column reaching the public payload; a feed that is not reproducible; coverage rows that do not join |
| **Image builds** | a container that does not build, or one that lies about its health |
| **Pages payload** | the mockup becoming unservable; a documentation link pointing at nothing |

CI runs on the same Python the image ships. Both are pinned to the same version,
and they are changed together — testing on one runtime and deploying another is
how a working test suite ships a broken container.

### Two jobs assert the opposite of what you would expect

**Data quality asserts the fixture FAILS.** `tests/fixtures/` holds 32 outlets
and 88 coverage records sampled from real prototype data and chosen to contain
every known defect. The job fails if the run comes back clean, and additionally
requires four rules to fire by name. A green run there would mean detection had
regressed, not that the data improved.

**Image builds asserts `/_health` returns 503.** The container is started with a
deliberately unreachable database. 503 is the correct answer — the service is up
and honest about being unable to serve. A 200 would mean the health check does
not check anything, which is worse than having none, because Cloud Run would keep
routing traffic to a broken revision.

### One rule set, two callers

The rules in [`checks/rules.py`](../checks/rules.py) are pure functions. CI runs
them against fixtures; `publish` runs the same functions against the live export.
A defect cannot reach the public feed by taking a different code path.

`export_columns_allowlisted` is the one that matters most: a field not on the
public allowlist fails the publish. That is what stops an admin-only column
reaching the public site when someone adds it to the model.

## 3. Deploy to GCP

Triggered by a merge to `main`. Documentation-only merges are skipped —
`paths-ignore` covers `**.md`, `docs/`, the mockup, issue templates and the
pre-commit config, because none of them are in the image.

1. **Authenticate** via Workload Identity Federation. No stored credentials, and
   the provider is bound to this repository by an attribute condition.
2. **Dependency image**, tagged with a hash of `requirements.txt`. Rebuilt only
   when that file changes, so "have the dependencies changed?" is a registry
   lookup rather than a guess. A normal deploy pushes about 4MB.
3. **Build and push** the application image, tagged with the commit SHA.
4. **Migrate and configure**, as a Cloud Run *job*, **before traffic shifts** —
   never as a side effect of the service starting, because two revisions racing
   to migrate is a bad night.
5. **Deploy** the service.
6. **Assert the service is reachable.** `gcloud` reports a refused IAM binding as
   a *warning* and exits zero; the first real deploy therefore reported success
   while every request was rejected with 403 before reaching Django. This step
   fails the build instead.
7. **Smoke test** `/_health` for 200.

Rolling back is a traffic shift, not a rebuild — but migrations do not roll back
with it. See [runbook.md](runbook.md).

## 4. Publishing the feed

Separate from the deploy, because the public site reads a static payload rather
than the database. `publish-qa.yml` fires on:

- **the admin's "Publish the public feed now" action** (a repository dispatch)
- **every completed Deploy**
- **a daily schedule**, 11:00 UTC — before anyone starts editing
- manual dispatch

It builds the feed, runs the same rules against it, and force-pushes an orphan
`gh-pages` branch. That branch therefore has no history, which matters when
something wrong is published — see [runbook.md](runbook.md).

## What is not gated

Worth knowing where the guarantees stop:

- **The mockup and the WordPress widget are not tested end to end.** CI checks the
  mockup file is present and servable, not that it renders.
- **No deploy runs against a staging environment.** `main` goes to production.
  The gates above are what stands in for a staging soak.
- **Nothing measures test coverage.** 281 tests run; what they miss is unknown.
