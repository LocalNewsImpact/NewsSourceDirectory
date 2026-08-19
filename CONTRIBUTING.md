# Contributing

## Getting a local environment

```bash
git clone https://github.com/LocalNewsImpact/NewsSourceDirectory.git
cd NewsSourceDirectory
make setup
```

`make setup` creates a virtualenv, installs dependencies, writes `.env` from
`.env.example`, installs the Node packages, and starts Postgres in Docker on port
5434. It is safe to rerun.

You need Python 3.11+, Docker, and Node 22+. Nothing else, and no GCP access —
the whole project runs locally against fixtures.

```bash
make run       # the admin at http://localhost:8000/admin/
make superuser # a login for it
make check     # everything CI runs
make test      # unit tests, no database
make fmt       # apply formatting and safe fixes
make help      # all targets
```

`make setup` migrates and seeds the controlled vocabularies, so the dropdowns are
populated on a fresh checkout. Seeding them matters: empty dropdowns are how the
source data ended up with "Public Broadcasting" beside "Public Broadcast".

Port 5434 is deliberate: 5432 is usually a system Postgres and 5433 belongs to
the crawler's test container, so this will not collide with other work.

## Tests

**Unit** tests need nothing. They cover the data-quality rules, the identity
rule, the feed builder, and the mockup's structure.

**Integration** tests are marked `@pytest.mark.integration` and need Postgres:

```bash
make test-integration
```

The split exists so a new contributor gets a green `make test` before Docker is
working. CI runs both on every branch.

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
