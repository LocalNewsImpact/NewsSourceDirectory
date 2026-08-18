# News Source Directory

A registry of local news outlets for the Local News Impact Consortium: a curated
database, an admin interface for editing it, and an embeddable public directory
for [localnewsimpact.org](https://www.localnewsimpact.org/).

Scale is small and fixed: **~5,000 rows**. Every decision below follows from that.

## Architecture

```
Workspace group --IAP--> Django admin (Cloud Run) --> Cloud SQL   [web project]
                                                          |
                                             publish job  |
                                                          v
                          GCS + Cloud CDN:  widget.js, sites.json
                                                          |
                                    WP page <-------------+-------------> crawler
                                 [lnic-directory]                        (later)
```

| Piece | Choice |
|---|---|
| Source of truth | Cloud SQL Postgres, smallest tier |
| Admin | Django admin on Cloud Run, behind IAP |
| Bulk edit | `django-import-export` — CSV in/out with a dry-run diff before commit |
| Audit | `django-simple-history` — per-field history and revert |
| Auth | IAP restricted to a Google Workspace group |
| Public directory | Static JSON + JS widget on GCS/Cloud CDN, embedded in WordPress |
| Search / filter / export | Entirely client-side |

Running cost: roughly **$25/month**.

### Why static for the public side

5,000 rows is about 150–250KB gzipped. The browser loads the whole dataset once
and does its own search, filtering, sorting and CSV export. No API service, no
read replica, no query load, nothing to keep up.

### Why Django when the crawler is FastAPI

Not a framework preference. It is `django.contrib.admin` +
`django-import-export` + `django-simple-history` + the built-in permission model
— which together are roughly the entire application. The cost is a second web
framework in the org, which is real and was accepted deliberately. If that trade
is revisited, the alternative is `sqladmin`/`starlette-admin` on FastAPI, not Flask.

## Relationship to the crawler

[MizzouNewsCrawler](https://github.com/LocalNewsImpact/MizzouNewsCrawler) is a
**separate system with a separate GCP project**. This repo shares no
infrastructure with it and needs no access to it. That separation is the point:
contributors here never touch the crawler's production project.

The two overlap in subject matter only. Eventually the crawler may be pointed at
subsets of this registry, so two things are built in from the start:

- **`domain_normalized`** — the registrable domain, lowercased, no scheme, no
  `www.`, indexed, stored separately from the display URL. This is the only
  reliable join key between the two systems. Names and cities are not: the
  crawler's own wire-misattribution bug turned on `emissourian.com` and
  `missourian.com` being one organization while `kansascity.com` and
  `kansas.com` are two.
- **Collections** — a real join table, not tags. A collection is the unit handed
  to the crawler, where its slug becomes a crawler `dataset` slug and the outlet
  UUID lands in `dataset_sources.legacy_host_id`, which is uniquely constrained
  per dataset and so makes re-ingest idempotent.

Flow is **one-way**: registry upstream, crawler downstream, no write-back. When
the crawler learns something the registry should know — dead domain, moved URL —
it surfaces as a report for a human to action in the admin.

Both consumers read the same published export from the bucket, so the crawler
needs no credential into this project's database.

## Public vs. admin columns

The published export carries only public directory fields. Operational and
internal fields stay in the admin. From the crawler's own Missouri export,
`status` and `paused_reason` ("Automatic pause after 5 consecutive cycles with
no articles discovered") are examples of fields that must not reach the public
JSON. The export query names an explicit column allowlist rather than `SELECT *`,
so a future schema addition cannot silently publish something new.

## WordPress embedding

localnewsimpact.org runs **Divi**. The directory mounts into the light DOM with
`.lnic-dir-*` prefixed classes so it inherits the site's fonts and link colors,
placed by a small shortcode plugin (`[lnic-directory]`) alongside the existing
`lnic-form-plugin`. The GCS bucket needs CORS allowing the site origin.

Design tokens taken from the live `/studies/` page:

| Token | Value |
|---|---|
| Accent | `#66cef6` |
| Link | `#0073aa`, bold, underline on hover |
| Border | `1px solid #ddd` |
| Header row | `#f2f2f2`, bold, `#333` |
| Cell padding | `12px 8px`, left aligned |
| Fonts | Montserrat (headings), Lato (body) |

The `/studies/` table renders in Arial, which is the sheet plugin's default
rather than a design decision; the directory uses the site fonts instead.

## Mockup

[`mockup/index.html`](mockup/index.html) is a working, self-contained prototype:
159 real Missouri outlets from the crawler's live source export, with search,
facets, sorting, paging and CSV export all running client-side.

`frequency` is absent because it is empty for all 160 rows in the real export —
shown as missing rather than faked.

## Security notes

Two things that are easy to get wrong and are not optional:

1. Verify the **`X-Goog-IAP-JWT-Assertion` signature**, not the plain
   `X-Goog-Authenticated-User-Email` header, which is spoofable by anything that
   reaches the service directly.
2. Set Cloud Run ingress to **internal-and-load-balancer**, so the service cannot
   be reached except through IAP. Without this, point 1 is the only thing between
   the internet and the admin.

## Status

Nothing is built yet. Next up:

- [ ] Schema — outlet fields, the collection join table, `domain_normalized`, and
      the public/admin column split
- [ ] Django project + admin, import/export and history wired up
- [ ] Terraform or scripted setup for the GCP project, Cloud SQL, IAP, bucket
- [ ] Publish job: DB to versioned JSON in the bucket
- [ ] Widget build and the WordPress shortcode plugin
