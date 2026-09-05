# Pipeline

Three gates between an edit and production.

```
local          make check
  ↓ push (any branch)
CI             8 required jobs
  ↓ merge to main (pull request, 1 approval)
  ↓ tag a release, bump the pin in Datadesk
Deploy         in Datadesk: build → migrate → candidate → health check → shift
  ↓
Publish        static feed to gh-pages
```

## 1. Local

```bash
make check        # lint, format, the whole suite, the floor — what CI runs
make test         # the suite on Postgres, with coverage and the floor
make e2e          # browser tests against the mockup
```

`make test` starts the Postgres container itself, runs the migrations check
and every test, and hands `coverage.xml` to `lnic_contracts.coverage_floor` —
the one floor every repository in the suite is held to, kept in
[lnic-contracts](https://github.com/LocalNewsImpact/lnic-contracts), not here.
Tests that need the database are marked `@pytest.mark.integration`; the rest
run without one, so `pytest -m "not integration"` is a quick loop before
Docker is up. It is a subset, and the floor is not judged on it.

Port 5434 avoids 5432 (the crawler), 5433 (the crawler's scratch container)
and 5435 (datadesk's test container).
Two checkouts of this repository share one database container — see
[CONTRIBUTING.md](../CONTRIBUTING.md).

## 2. CI

Runs on every push to every branch, and on pull requests. All eight jobs are
required to merge.

| Job | Fails when |
|---|---|
| Lint | `ruff check` or `ruff format --check` fails |
| Tests | any of 163 unit tests fails |
| Integration | any of 118 integration tests fails, a model change has no migration (`makemigrations --check`), or coverage drops below the floor |
| Data quality | the defect fixture passes, or one of four named rules stops firing |
| Public feed | the feed carries a non-allowlisted column, is not byte-reproducible, or has coverage rows that do not join to an outlet |
| Image builds | either Docker stage fails, or the container's `/_health` does not return 503 without a database |
| Browser | the directory does not render, search does not narrow the set, or export produces no CSV |
| Pages payload | the mockup is missing or oversized, or a documentation link points at a missing file |

Two jobs assert failure rather than success:

- **Data quality** runs the rules against `tests/fixtures/`, which is 32 outlets
  and 88 coverage records containing every known defect. The job fails if the run
  is clean, and requires `no_placeholder_domain`, `merge_requires_review`,
  `no_header_artifacts` and `no_url_in_medium` to fire by name. A clean run means
  detection regressed.
- **Image builds** starts the container with an unreachable database and requires
  `/_health` to return **503**. A 200 would mean the health check does not query
  the database, and Cloud Run would route traffic to a revision that cannot
  serve.

CI and `Dockerfile.base` pin the same Python version. Change them together.

### Rules run in two places

`checks/rules.py` holds pure functions. CI runs them against fixtures; `publish`
runs the same functions against the live export. There is no second code path to
the feed.

`export_columns_allowlisted` fails a publish on any column not in
`PUBLIC_FIELDS`. This is what prevents a new model field reaching the public
directory.

## 3. Deploy — in Datadesk, not here

Nothing in this repository deploys or migrates. `sources-admin` runs Datadesk's
image with `SERVICE_ROLE=sources`, and this package reaches it by being pinned
in Datadesk's `requirements.txt`:

```
tag a release here  →  bump the pin in Datadesk  →  Datadesk's deploy
```

Datadesk's `deploy.yml` builds the image once and rolls out both consoles,
proving its own before touching this one:

| Step | Detail |
|---|---|
| 1. Authenticate | Workload Identity Federation, as `github-deploy@lnic-datadesk`, which holds `run.developer` in `lnic-source-directory` |
| 2. Images | Dependency image keyed to a `requirements.txt` hash; application image tagged with the commit SHA |
| 3. Datadesk | Migrate, deploy a no-traffic candidate, prove `/_health`, shift, smoke test |
| 4. Migrate this schema | Cloud Run **job**: `migrate directory`, `configure_site`, `check_data` |
| 5. Deploy | `--no-traffic --tag candidate` — the revision serves nobody yet |
| 6. Check reachability | Fails if no `run.invoker` binding exists |
| 7. Prove the candidate | `/_health` on the candidate's tagged URL must return 200 |
| 8. Shift traffic | `update-traffic --to-latest`, then smoke test the public URL |

Step 4 names the app. Both consoles share one ledger in
`public.django_migrations`, but the job runs with `search_path=directory,public`,
so a bare `migrate` would let another app's unapplied migration create its table
in the `directory` schema. Naming the app is what makes that impossible — it
replaced a database router that used to live here.

Step 6 exists because `gcloud` reports a refused IAM binding as a warning and
exits 0. The first production deploy therefore reported success while every
request returned 403.

Step 7 is what a staging environment would otherwise do. If the candidate fails
its health check, traffic stays on the previous revision.

Rollback is a traffic shift, not a rebuild. Migrations do not roll back with it —
see [runbook.md](runbook.md).

## 4. Publish

The public site reads a static payload, not the database, so publishing is
separate from deploying. `publish-qa.yml` runs on:

- the admin's "Publish the public feed now" action (a repository dispatch)
- completion of any Deploy run
- a daily schedule at 11:00 UTC
- manual dispatch

It builds the feed, applies the same rules, and force-pushes an orphan
`gh-pages` branch. That branch holds one commit, so a bad publish cannot be
reverted with git — see [runbook.md](runbook.md).

## Coverage

The Integration job measures the whole suite and fails below the floor in
`pyproject.toml`. Current: **80.0%** measured, **78%** floor. The floor is a
ratchet against decay, not a target.

At 0%: `publish.py`, `ensure_admin.py`, `check_data.py` — the commands that
write the public feed, grant admin access, and report data quality. Cover these
before raising the floor.

## Not covered

| Gap | Consequence |
|---|---|
| The WordPress plugin has no tests | The Browser job drives the mockup, which shares the plugin's logic, but the plugin lives in `LocalNewsImpact/lnic-wordpress` and is untested there |
| No staging environment | A candidate revision passing one health check is the substitute; there is no soak |
| Migrations are not rehearsed | They run against production before traffic shifts, and rolling traffic back does not revert them |
