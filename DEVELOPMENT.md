# Development plan

Sequenced so that each milestone is independently useful and nothing is built on
an unreviewed assumption. The schema is the one hard blocker; almost everything
else can proceed in parallel once it settles.

## Environment facts

Confirmed against the live org, not assumed:

| | |
|---|---|
| Organization | `localnewsimpact.org` — id `293319414046`, customer `C04iy3g4y` |
| Billing | `011142-05FA4C-0FCA10` (Kiesow - LNIC Billing), open |
| Existing projects | 7, including `mizzou-news-crawler` in the same org |
| Naming convention | kebab-case, e.g. `lnic-form-service-account` |
| Region | `us-central1`, matching the crawler |

**Domain Restricted Sharing is enforced**, allowing only customer `C04iy3g4y`.
A personal Google account cannot hold any IAM role in this org — the grant is
refused at the API. Anyone who needs GCP access needs a `@localnewsimpact.org`
identity first. This is a hard constraint, not a preference.

---

## M0 — Schema review  ·  blocks everything

**Deliverable** `schema/models_draft.py` reviewed and agreed.

Open questions worth settling before code depends on them:

1. Is the identity rule right? `host + first meaningful path segment`, falling
   back to `slug(name)|state` where there is no URL.
2. Do `Medium` and `Category` stay separate axes, or collapse?
3. Does `Outlet` carry one `state`, or is multi-state real for any outlet once
   the bad merges are undone?
4. Which coverage fields roll up to `Outlet` — `ownership`, `founded`,
   `closed_date` are proposed.

**Done when** the models are agreed and the first migration can be written.

---

## M1 — GCP bootstrap  ·  can start now, parallel with M0

**Deliverable** an empty but complete project.

1. Create `lnic-news-directory` under the org, on the LNIC billing account.
2. Enable: `run`, `sqladmin`, `artifactregistry`, `cloudbuild`, `iap`,
   `secretmanager`, `storage`, `cloudscheduler`.
3. Cloud SQL: Postgres 16, Enterprise, `db-custom-1-3840`, **private IP**,
   automated backups + point-in-time recovery. Back up the database; the bucket
   needs none, since every byte in it is reproducible by rerunning `publish`.
4. Artifact Registry repository for the app image.
5. GCS bucket, uniform access, public read on the `feed/` prefix only, CORS
   allowing the WordPress origin.
6. Workload Identity Federation pool + provider + deploy service account, scoped
   to this repo — so deploys run from GitHub Actions and no human holds
   production write.
7. Secrets: database password, Django `SECRET_KEY`.
8. Cloud Identity account for Matt at `@localnewsimpact.org`; a
   `lnic-directory-editors@` group for IAP.

**Done when** `terraform plan` (or the scripted equivalent) is clean and the
bucket serves a hand-uploaded `manifest.json`.

**Decisions needed** project id; whether IaC is Terraform or a documented script.

---

## M2 — Django skeleton

**Deliverable** the admin running locally against Postgres.

Models from M0, `django-import-export`, `django-simple-history`, WhiteNoise,
Gunicorn. Admin configured for the work that matters: `CoverageRecord` inline on
the outlet form, a `needs_review` list filter, merge and split actions.

**Depends on** M0. **Done when** an editor can add and edit an outlet locally.

---

## M3 — Import and rebuild  ·  the real work

**Deliverable** `import_source` and `rebuild_outlets`.

1. `import_source <gcs-uri>` reads xlsx/csv into `CoverageRecord` with
   provenance, wrapped in a `SourceImport` so a bad import reverses as a unit.
2. `rebuild_outlets` derives outlets by the identity rule, flags conflicts.
3. Run against the real prototype data and compare: expect ~2,983 outlets against
   the prototype's 2,103, and 222 rows flagged for review.
4. Vocabulary mapping — the 18 medium values onto ~7, states onto full names.

**Depends on** M2. **Done when** the rules report zero errors on derived data, or
every remaining error is deliberate and flagged.

---

## M4 — Publish

**Deliverable** `publish` writing the feed to the bucket.

The generator already exists and is tested; this milestone is the Django command
that feeds it from the database and uploads with the right cache headers —
`no-cache` on `manifest.json`, `public, max-age=31536000, immutable` on the
hashed files.

**Depends on** M1, M3. **Done when** the feed is live in the bucket and the
manifest round-trips.

---

## M5 — Widget and WordPress

**Deliverable** the directory embedded on localnewsimpact.org.

Vite + Preact + MiniSearch, built from the mockup's behaviour, reading the feed.
Coverage loads lazily on drill-down. Then a `[lnic-directory]` shortcode plugin
alongside the existing `lnic-form-plugin`.

**Depends on** M4. **Done when** it renders inside a Divi page and matches the
site's type and colour.

---

## M6 — Deploy pipeline

**Deliverable** push to `main` deploys.

GitHub Actions via WIF: build image, push to Artifact Registry, run `migrate` as
a Cloud Run Job, deploy the service, smoke test. IAP enabled directly on Cloud
Run, ingress locked to internal-and-load-balancer, and the
`X-Goog-IAP-JWT-Assertion` signature verified rather than the plain email header.

**Depends on** M1, M2.

---

## M7 — The review queue  ·  people, not code

222 suspected bad merges to confirm or split, 138 missing domains, 103 missing
media. This is curation work in the admin and it is the point of the whole
exercise — the software exists to make it possible.

**Depends on** M2, M3.

---

## M8 — Collections and the crawler handoff

Only once the registry is clean. A `Collection` slug becomes a crawler dataset
slug; outlet ids land in `dataset_sources.legacy_host_id`. One-way, no write-back.

---

## Suggested order

```
M0 schema  ─┬─> M2 django ─┬─> M3 import/rebuild ─> M4 publish ─> M5 widget
            │              └─> M6 deploy                            │
M1 gcp ─────┴──────────────────────────────────────────────────────┘
                                     └─> M7 review queue ─> M8 collections
```

M0 and M1 run in parallel and are the two things to start now.
