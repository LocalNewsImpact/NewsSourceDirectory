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
| Database | Postgres 16, Cloud SQL Enterprise, smallest **dedicated** core | Shared-core has no SLA; see [Sizing](#database-sizing) |
| Admin | Django 5.x + Gunicorn on Cloud Run | Inlines make the merge review tractable — see below |
| Bulk edit | `django-import-export` | Reads the source `.xlsx`/`.csv` with a dry-run diff before commit |
| Audit | `django-simple-history` | Per-field history and revert, essential during remediation |
| ETL | management commands run as **Cloud Run Jobs** | Same image, different entrypoint; no request timeout |
| Auth | IAP restricted to a Google Workspace group | Editors need no GCP IAM beyond `iap.httpsResourceAccessor` |
| Public widget | Vite + **Preact** + MiniSearch | ~30KB bundle; React would outweigh the data |
| Hosting | Cloud Run (admin), GCS (widget) | Scale-to-zero admin, static public side |

Running cost: **~$15/month**. See [Cost](#cost).

### Database sizing

`db-f1-micro` and `db-g1-small` are shared-core and carry **no Cloud SQL SLA**;
their CPU is burstable and can be throttled, which shows up as an admin page that
occasionally stalls. They are a testing tier.

The smallest dedicated core (`db-custom-1-3840`, 1 vCPU / 3.75GB) is roughly
$50/month against ~$11, and gets the 99.95% single-zone SLA.

Capacity is not the reason to choose it. 2,103 outlets and 8,561 coverage records
is a rounding error for Postgres — at a hundred times this size the database still
would not be the constraint, and the real ceiling is concurrent admin users, which
is under ten. Choose dedicated core for the SLA and predictable latency, not for
headroom. Nothing in the architecture changes either way.

### Admin hostname

The admin is served at **`directory.localnewsimpact.org`**, not a `run.app` URL.

That requires a global external Application Load Balancer in front of Cloud Run:
IAP on a bare Cloud Run service only protects the `run.app` hostname, and Cloud
Run domain mappings do not carry IAP. So the admin path is

```
directory.localnewsimpact.org
  -> A record (Route 53)      overrides the *.localnewsimpact.org wildcard
  -> global external ALB      Google-managed certificate, IAP on the backend
  -> serverless NEG
  -> Cloud Run (ingress: internal-and-cloud-load-balancing)
```

The ingress setting matters as much as IAP: without it the `run.app` URL stays
reachable and walks straight past the load balancer, and therefore past IAP.

This costs ~$18/month for the forwarding rule. The **feed is unaffected** — it
still serves directly from the bucket, so the charge is paid once, for the admin,
not for the public side.

DNS is Route 53, and `*.localnewsimpact.org` currently resolves to the WordPress
host (50.16.132.48). A record for the exact name takes precedence, so no wildcard
change is needed. Create it before the certificate is requested: a Google-managed
certificate will not issue until the hostname already resolves to the load
balancer address.

### App server

Gunicorn, WSGI, with the Cloud Run shape:

```
gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 config.wsgi:application
```

One worker because Cloud Run bills per instance and handles concurrency itself;
threads because admin requests are I/O-bound on the database; `--timeout 0`
because Cloud Run enforces its own request deadline and a second one only
produces confusing 502s. Serve static files with WhiteNoise — without it the
Django admin loads unstyled on Cloud Run.

### ETL as Cloud Run Jobs

Yes. The three management commands run as Cloud Run Jobs built from the same
image as the service, with a different entrypoint:

| Job | Trigger |
|---|---|
| `migrate` | on deploy, before traffic shifts |
| `import_source <gcs-uri>` | manual, or Cloud Scheduler |
| `rebuild_outlets` | manual, after an import |
| `publish` | on save, or scheduled |

Jobs are the right shape because they run to completion with no request timeout,
and can be given more memory than the service — pandas reading a spreadsheet
wants 1–2GB while the web service is comfortable at 512MB.

One split worth keeping: interactive spreadsheet uploads go through
`django-import-export` in the admin, because the editor needs the dry-run diff in
front of them. Jobs handle the batch and scheduled paths.

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

**No Cloud CDN in front of the feed.** It requires an external Application Load
Balancer whose forwarding rule alone is ~$18/month. The feed serves straight from
the bucket with CORS, and at 73KB gzipped a CDN buys almost nothing. If a custom
domain for the feed is wanted later, Cloudflare's free tier goes in front.

The **admin** is the exception, and does need a load balancer — see below.

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

## Public data feed

`python -m feed` writes a content-addressed static feed:

```
feed/manifest.json                 small, short cache TTL, always revalidated
feed/sites.<sha8>.json             immutable, cache for a year
feed/search-index.<sha8>.json      immutable — optional, see below
```

Content hashing is what makes this work on a bare bucket with no CDN: the
manifest is the only file that ever needs revalidating, everything it points at
is immutable. A publish writes new hashed files and swaps the manifest, so a
reader never sees a half-updated feed.

The build is **deterministic** — sorted keys, sorted rows, hash independent of
build time — so an unchanged dataset produces an unchanged hash and no pointless
redeploy. Projection onto `PUBLIC_FIELDS` happens in one place, and the publish
**refuses to write** when any rule errors unless `--allow-errors` is passed
explicitly.

```bash
python -m feed outlets.csv --coverage coverage.csv --out dist/feed
npm run build:index          # optional, see below
```

### The prebuilt MiniSearch index is not worth shipping

It is implemented (`tools/build-search-index.mjs`, in Node so the serialised form
always matches the library version the widget loads) but **off by default**,
because the measurement does not support it:

| | Gzipped | Time |
|---|---|---|
| `sites.json` alone, index built in browser | **73KB** | 16ms to index 2,103 docs |
| plus prebuilt `search-index.json` | 205KB | 12ms to load |

Shipping the index costs **132KB gzipped to save 4ms**. Build it in the browser.

Revisit if the registry grows by an order of magnitude, or if indexing time
becomes visible on low-end phones — at which point the generator is already here
and the decision is a flag, not a rewrite.

## CI and data quality

`.github/workflows/ci.yml` runs five jobs on every push and pull request.

| Job | Checks |
|---|---|
| Lint | `ruff check` and `ruff format --check` |
| Tests | 60 tests over the rules and the mockup |
| Data quality | the rules against a fixture of real prototype data |
| Public feed | feed builds, carries no admin columns, is reproducible |
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
| Cloud SQL Postgres `db-custom-1-3840` + 10GB SSD | ~$50 |
| Load balancer for `directory.localnewsimpact.org` | ~$18 |
| Cloud Run (scale-to-zero) | $0–2 |
| GCS storage and egress | ~$0.50 |
| Artifact Registry, Secret Manager, logs | <$1 |
| **Total** | **~$70** |

Two of those are deliberate upgrades from the ~$15 first estimate: a dedicated
core for the SLA rather than a shared core with none, and a load balancer to put
the admin on a real hostname. Both are single variables in
`infra/bootstrap.sh`.

`min-instances=1` to remove Django cold starts adds ~$10. Cloud SQL HA roughly
doubles the database line.

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

- [x] CI: lint, tests, data-quality rules, feed build
- [x] Public static feed generator
- [ ] Schema review — [`schema/models_draft.py`](schema/models_draft.py)
- [ ] Django project, admin, import/export and history wired up
- [ ] `import_source`, `rebuild_outlets`, `publish` management commands
- [ ] GCP project, Cloud SQL, IAP, bucket
- [ ] Widget build and the WordPress shortcode plugin
- [ ] Deploy workflow via Workload Identity Federation
- [ ] Work the review queue: 222 suspect merges, 138 missing domains, 103 missing media
