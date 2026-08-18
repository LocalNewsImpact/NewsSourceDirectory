# News Source Directory

A registry of local news outlets for the Local News Impact Consortium: a curated
database, an admin interface for editing it, and an embeddable public directory
for [localnewsimpact.org](https://www.localnewsimpact.org/).

It succeeds the [`mwe400/LocalNewsDatabase`](https://github.com/mwe400/LocalNewsDatabase)
Streamlit prototype — **2,103 outlets and 8,561 coverage records**. Every feature
of that prototype is preserved; see [MIGRATION.md](MIGRATION.md) for the parity
inventory and the data problems that have to be fixed on the way.

## Architecture

```
Workspace group --IAP--> Django admin (Cloud Run) --> Cloud SQL   [web project]
                                                          |
                                             publish job  |
                                                          v
                          GCS:  widget.js, sites.json  (204KB gzipped)
                                                          |
                                    WP page <-------------+-------------> crawler
                                 [lnic-directory]                        (later)
```

## Stack

| Layer | Choice | Why |
|---|---|---|
| Database | Postgres 16 on Cloud SQL, smallest tier | Replaces the committed SQLite file |
| Admin | Django 5.x + `django.contrib.admin` | Inlines make the merge review tractable — see below |
| Bulk edit | `django-import-export` | Reads the source `.xlsx`/`.csv` with a dry-run diff before commit |
| Audit | `django-simple-history` | Per-field history and revert, essential during remediation |
| ETL | pandas, inside management commands | Keeps what `build_demo.py` did well, out of the request path |
| Auth | IAP restricted to a Google Workspace group | Editors need no GCP IAM beyond `iap.httpsResourceAccessor` |
| Public widget | Vite + **Preact** + MiniSearch | ~30KB bundle; React would outweigh the data |
| Hosting | Cloud Run (admin), GCS (widget) | Scale-to-zero admin, static public side |

Running cost: **~$15/month**. See [Cost](#cost).

### Why Django when the crawler is FastAPI

Not a framework preference — it is `django.contrib.admin` + `django-import-export`
+ `django-simple-history` + the built-in permission model, which together are
most of the application.

The deciding factor is the merge review. Fixing the prototype's dedupe means
opening one outlet and seeing its child coverage records — all 134 raw names
under `patch.com` — then splitting them. Admin inlines do exactly that out of
the box. In FastAPI + `sqladmin`, inlines and bulk actions are the parts you
would hand-build, and they are the parts most needed here.

The cost is a second web framework in the org. That is real and was accepted
deliberately. If the trade is revisited, the alternative is `sqladmin` or
`starlette-admin` on FastAPI — not Flask.

### Why static for the public side

The public payload is 65KB gzipped for outlets, 204KB with coverage records
included. The browser loads it once and does its own search, filtering, sorting
and CSV export. No API service, no read replica, no query load.

**No Cloud CDN.** It requires an external Application Load Balancer whose
forwarding rule alone is ~$18/month — more than the database. Serve from the
bucket directly with CORS. If a custom domain and edge caching are wanted later,
Cloudflare's free tier goes in front. Same trap on the admin: enable IAP
**directly on Cloud Run**, not via a load balancer.

## Data model

Two tables, which is better than one — it makes the public/admin split
structural rather than a per-column flag.

- **`Outlet`** — curated outlet profiles. Publishes to `sites.json`.
- **`CoverageRecord`** — the source rows, verbatim, with `source_file` /
  `source_sheet` provenance. **Admin only.** Never edited by derivation; every
  Outlet field must be reproducible from it.
- **`Medium`, `Category`, `State`** — controlled vocabularies. Once medium is a
  foreign key, a URL cannot be stored in it and the header-row class of error
  becomes structurally impossible.
- **`Collection`** — a named subset, the unit handed to the crawler.

A draft is in [`schema/models_draft.py`](schema/models_draft.py), written
against the real columns of both CSVs.

### Identity is not the domain

The prototype deduplicated on the bare registrable domain, which merged 1,102
distinct outlets into 222 rows — `patch.com` alone collapsed 134 outlets into
one. `domain` is kept and indexed because it is the join key to the crawler, but
it is **not unique**. Identity is `host + first meaningful path segment`, or
`slug(name)|state` when there is no URL. Details and caveats in
[MIGRATION.md](MIGRATION.md).

## Relationship to the crawler

[MizzouNewsCrawler](https://github.com/LocalNewsImpact/MizzouNewsCrawler) is a
**separate system in a separate GCP project**. This repo shares no infrastructure
with it and needs no access to it. Contributors here never touch the crawler's
production project.

Eventually the crawler may be pointed at subsets of this registry. Flow is
**one-way** — registry upstream, crawler downstream, no write-back. A
`Collection` slug becomes a crawler `dataset` slug, and the Outlet id lands in
`dataset_sources.legacy_host_id`, which is uniquely constrained per dataset and
so makes re-ingest idempotent. When the crawler learns something the registry
should know — dead domain, moved URL — it surfaces as a report for a human, not
an automated write.

Both consumers read the same published export from the bucket, so the crawler
needs no credential into this project's database.

## Public vs. admin columns

The export names an explicit column allowlist rather than `SELECT *`, so a
future schema addition cannot silently publish something new. Operational fields
stay in the admin — in the crawler's Missouri export, `status` and
`paused_reason` ("Automatic pause after 5 consecutive cycles with no articles
discovered") are the kind of field that must never reach the public JSON.

## WordPress embedding

localnewsimpact.org runs **Divi**. The directory mounts into the light DOM with
`.lnic-dir-*` prefixed classes so it inherits the site's fonts and link colours,
placed by a small shortcode plugin (`[lnic-directory]`) alongside the existing
`lnic-form-plugin`. The bucket needs CORS allowing the site origin.

Design tokens taken from the live `/studies/` page:

| Token | Value |
|---|---|
| Accent | `#66cef6` |
| Link | `#0073aa`, bold, underline on hover |
| Border | `1px solid #ddd` |
| Header row | `#f2f2f2`, bold, `#333` |
| Cell padding | `12px 8px`, left aligned |
| Fonts | Montserrat (headings), Lato (body) |

The `/studies/` table renders in Arial, which is that sheet plugin's default
rather than a design decision; the directory uses the site fonts instead. That
page is itself a Google Sheet rendered as `<table class="google-sheet-table">`
with no search, filter or export — a candidate to move onto this widget later.

## Mockup

[`mockup/index.html`](mockup/index.html) is a working, self-contained prototype
carrying the full dataset and every feature of the Streamlit app: metric tiles,
keyword search, all three multi-select filters, outlet cards, the coverage table
and the data explorer, with CSV export of whatever is on screen. Card/table
toggle, sortable columns, filter chips and pagination are additions.

## CI and data quality

`.github/workflows/ci.yml` runs four jobs on every push and pull request.

| Job | Checks |
|---|---|
| Lint | `ruff check` and `ruff format --check` |
| Tests | 60 tests over the rules and the mockup |
| Data quality | the rules against a fixture of real prototype data |
| Pages payload | the mockup stays servable, internal doc links resolve |

### One rule set, two callers

The rules live in [`checks/rules.py`](checks/rules.py) as pure functions. CI runs
them against fixtures; the `publish` command will run the same functions against
the live export. A defect cannot reach `sites.json` by taking a different code
path.

```bash
python -m checks outlets.csv --coverage coverage.csv
python -m checks outlets.csv --export sites.json   # before publishing
```

**ERROR** blocks a publish. **WARN** is counted and reported but does not block —
a missing county is curation backlog, not corruption, and a permanently red
pipeline gets ignored.

The single most important rule is `export_columns_allowlisted`: a column not on
the public allowlist fails the publish. That is what stops an admin field such as
`paused_reason` reaching the public site when someone adds it upstream.

### The fixture is expected to fail

[`tests/fixtures/`](tests/fixtures/) holds 32 outlets and 88 coverage records
sampled from the real prototype data and chosen to contain every known defect.
The data-quality job asserts the run **fails** and that each named rule fires. A
clean run there means detection has regressed, not that the data got better.

Against the full prototype dataset the rules currently report:

| Rule | Errors |
|---|---|
| `merge_requires_review` | 222 |
| `state_not_abbreviated` | 73 |
| `no_header_artifacts` | 3 |
| `no_url_in_medium` | 2 |
| `no_placeholder_domain` | 2 |

That 222 is the same figure the migration analysis arrived at independently, which
is the point: the defect is now a test rather than a paragraph.

### Not yet wired

Deployment. When the Django app and GCP project exist, deploys should run from
GitHub Actions via Workload Identity Federation — as the crawler already does —
so no human holds production write access.

## Cost

| Line item | Monthly |
|---|---|
| Cloud SQL Postgres `db-f1-micro` + 10GB SSD | ~$11 |
| Cloud Run (scale-to-zero) | $0–2 |
| GCS storage | ~$0.10 |
| Egress, 10k page views | ~$0.30 |
| Artifact Registry, Secret Manager, logs | <$1 |
| **Total** | **~$13–15** |

`min-instances=1` to remove Django cold starts adds ~$10. Cloud SQL HA roughly
doubles the database line. `db-f1-micro` is shared-core and carries no Cloud SQL
SLA — fine for a few editors; an SLA-covered tier jumps to ~$50.

## Security notes

Two things that are easy to get wrong and are not optional:

1. Verify the **`X-Goog-IAP-JWT-Assertion` signature**, not the plain
   `X-Goog-Authenticated-User-Email` header, which is spoofable by anything that
   reaches the service directly.
2. Set Cloud Run ingress to **internal-and-load-balancer**, so the service cannot
   be reached except through IAP. Without this, point 1 is the only thing between
   the internet and the admin.

## Status

Nothing is built yet.

- [x] CI: lint, tests, data-quality rules
- [ ] Schema review — [`schema/models_draft.py`](schema/models_draft.py)
- [ ] Django project, admin, import/export and history wired up
- [ ] `import_source`, `rebuild_outlets`, `publish` management commands
- [ ] GCP project, Cloud SQL, IAP, bucket
- [ ] Widget build and the WordPress shortcode plugin
- [ ] Deploy workflow via Workload Identity Federation
- [ ] Work the review queue: 222 suspect merges, 138 missing domains, 103 missing media
