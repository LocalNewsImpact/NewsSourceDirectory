# Migrating the Local News Database prototype

Source: [`mwe400/LocalNewsDatabase`](https://github.com/mwe400/LocalNewsDatabase) —
a Streamlit prototype over a SQLite file, built by merging several state and
site-area spreadsheets.

Its shape is good and carries over almost directly. Its **outlet-level dedupe is
broken**, and fixing that is the substance of this migration.

## What is in the prototype

| Table | Rows | Role |
|---|---|---|
| `outlets` | 2,103 | deduplicated outlet profiles |
| `coverage_records` | 8,561 | the underlying source rows, with provenance |

`outlets_clean.csv` columns: `outlet_id, outlet_name, canonical_url, domain,
primary_medium, mediums, states, cities, counties, source_count, record_count,
source_files, search_text, dedupe_key`

`coverage_clean.csv` columns: `outlet_id, source_file, source_sheet,
outlet_name_raw, url, medium, state, county, city, notes, mun_id, gnis,
domains_set_length, article_length, ownership, ownership_type, founded,
closed_date, updated_on, newsbank_availability`

Restricted to public columns, the outlets table serialises to **454KB raw,
68KB gzipped** — comfortably inside the static-publish design.

## The blocker: dedupe collapses distinct outlets

`dedupe_key` is the bare registrable domain. Every outlet sharing a domain with
another was merged into one row, keeping whichever name sorted first.

| Domain | Distinct outlets merged | Surviving name |
|---|---|---|
| `patch.com` | 134 | Patch-Asbury Park |
| `no website` | 103 | Gleaner, The |
| `tapinto.net` | 69 | TAP into Barnegat/Waretown |
| `facebook.com` | 66 | The Aiken Leader |
| `hometownsource.com` | 32 | Sun Sailor |
| `dailyvoice.com` | 22 | Bergenfield Daily Voice |
| `bizjournals.com` | 5 | Atlanta Business Chronicle |

Measured across the whole table:

- **222 outlet rows (10.6%)** each merge more than one distinct raw outlet name
- those rows contain **2,712 coverage records — 31.7% of all records**
- **1,102 distinct names** are collapsed into those 222 rows
- the true outlet count is nearer **2,983**, so the table under-counts by ~30%

Two consequences worth stating plainly:

1. Outlets with no URL were given the literal string `no website` as their
   domain, so 103 unrelated outlets became one record. A second variant,
   `(no website)`, formed an 18-outlet bucket of its own.
2. Apparent multi-state coverage is an artefact of this, not a feature.
   "The Aiken Leader" spanning 11 states is 70 unrelated Facebook-only outlets
   in one row; `bizjournals.com` folds five distinct city business journals
   together. **Do not model `states` as a many-to-many to preserve** — it is
   damage to be undone.

The general lesson, which the crawler hit independently: a registrable domain is
a good join *hint* and a poor *identity*. Network publishers share one.

### Proposed identity rule

```
canonical_url present -> host + first path segment
                         (dropping generic segments: news, home, index, "")
canonical_url absent  -> slug(name) + "|" + state      # never merge on absence
```

`patch.com/new-jersey/asbury-park` and `patch.com/new-jersey/barnegat` separate
correctly; `gordongazettega.com/news` still resolves to `gordongazettega.com`.
This is a starting heuristic, not a settled answer — it should be run, measured,
and reviewed before being trusted.

## Other data issues

- **A header row was imported as data**: an outlet named `Outlet Name`, medium
  `Type`, state `State`. At least one source was parsed at the wrong offset.
- **Column shift** in another source: two rows carry URLs in `primary_medium`
  (`https://www.gordongazettega.com/news`, a Facebook URL).
- **`primary_medium` holds 18 values where ~7 are real** — `TV station`,
  `TV (Fox)`, `TV (CBS)`, `TV (NBC)`, `TV (Public)`, `Public Broadcast` vs
  `Public Broadcasting`. `Ethnic Outlets` and `Network Sites` are a different
  axis entirely and belong in their own field.
- **States mix codes and names** — `MS`, `VA`, `WV` alongside `Alabama`, `Georgia`.
- **Gaps**: 138 outlets have no domain, 103 no medium, 76 no state; cities are
  present on 65% and counties on 55%.
- **`build_demo.py` no longer reproduces the committed data.** It builds from
  the New Jersey and Montana spreadsheets only, off `/mnt/data/` sandbox paths,
  and its output columns predate the v4 CSVs (no `ownership`, `founded`,
  `closed_date`, `newsbank_availability`, `mediums`, `search_text`).

## Phases

### Phase 0 — land it, trust nothing

Import `coverage_clean.csv` unchanged into `CoverageRecord`, provenance intact.
Import `outlets_clean.csv` into `Outlet`, setting `needs_review = True` wherever
a row's children carry more than one distinct `outlet_name_raw` (222 rows).

Nothing is discarded and nothing is trusted. At the end of this phase the data
is in Postgres behind an authenticated admin with history enabled — which is
already better than a `.db` file committed to a repo.

### Phase 1 — re-derive outlets

Implement the identity rule, run `rebuild_outlets`, and compare against the
Phase 0 rows. Expect roughly 2,983 outlets. Conflicts — same identity, different
names — get flagged rather than silently resolved.

Coverage records keep their raw values permanently. Every derived outlet field
must be reproducible from them.

### Phase 2 — controlled vocabularies

`Medium` and `State` become lookup tables with foreign keys. This is what makes
the cleanup durable: once medium is an FK, a URL cannot be stored in it, and the
header-row class of error becomes structurally impossible rather than something
to re-clean after every import.

One-time mapping of the 18 medium values onto ~7, with anything unmappable
flagged. Move `Ethnic Outlets` and `Network Sites` to a separate `categories`
field.

Then editors work the review queue in the admin: 222 merges to confirm or split,
138 missing domains, 103 missing media. This is the work the admin exists for.

### Phase 3 — publish

`publish` writes public columns to `sites.json`, uploads to the bucket, and the
widget picks it up. Coverage records stay in the admin.

### Phase 4 — collections and the crawler handoff

Only once the registry is clean. See the README.

## Commands to build

```
import_source <file>     xlsx/csv -> CoverageRecord, provenance preserved
rebuild_outlets          derive Outlet via the identity rule, flag conflicts
publish                  public columns -> sites.json -> GCS
```

Together these replace `build_demo.py` and make the pipeline reproducible
outside a sandbox, which it currently is not.

## What to keep from the prototype

Three things are genuinely well judged and should carry over rather than be
reinvented:

- **`search_text`** — precomputing the searchable blob is right. Keep it
  denormalized, regenerate on save, feed it to MiniSearch in the widget.
- **`source_file` / `source_sheet` on every coverage row.** This provenance is
  what makes the merge review possible at all.
- **`record_count` / `source_count` rollups.** They are the signal that flags a
  suspect merge — `record_count: 162` on one Patch outlet is the tell.

## Feature parity: nothing is dropped

Streamlit the *runtime* is replaced. Every feature it provides is preserved.
The mockup in `mockup/` implements all of them against the real dataset, so
parity is demonstrable rather than asserted.

| Prototype feature (`app.py`) | Preserved as | Status |
|---|---|---|
| Hero title + description | Page header | in mockup |
| Metric: unique outlets | Metric tile — 2,103 | in mockup |
| Metric: coverage records | Metric tile — 8,561 | in mockup |
| Metric: states covered | Metric tile — 20 | in mockup |
| Metric: source files | Metric tile — 8 | in mockup |
| Keyword search over `search_text` | Search box, same fields | in mockup |
| State **multi**-select (via coverage join) | Multi-select facet, OR within facet | in mockup |
| Primary medium **multi**-select | Multi-select facet | in mockup |
| Source file **multi**-select (via coverage join) | Multi-select facet | in mockup |
| Outlet cards: name / domain / record + source counts | Card view, same fields | in mockup |
| Medium tag + up to 8 state tags | Pills, same 8-tag cap | in mockup |
| Cities / Counties / Source files rows | Card definition list | in mockup |
| "Open website" link | Card link, `target=_blank` | in mockup |
| Empty state message | Empty state + clear-filters link | in mockup |
| Sorted by outlet name | Default sort, plus sortable columns | in mockup |
| Download filtered outlets CSV | Export button, current filtered set | in mockup |
| Coverage Records tab | Coverage tab, all 20 columns | in mockup |
| Coverage search across raw name/city/county/state/notes | Same five fields | in mockup |
| Coverage state + source filters | Shared facets apply | in mockup |
| Download filtered coverage CSV | Export button on that tab | in mockup |
| Data Explorer: full outlets table | Explorer tab, all 12 columns | in mockup |
| Data Explorer: full coverage table | Explorer tab, all 20 columns | in mockup |
| `nan` / `None` display cleaning | Cleaned at import | in mockup |
| — | Card/table toggle | added |
| — | Filter chips with per-chip removal | added |
| — | Pagination | added |
| — | Sortable columns | added |
| Streamlit auth (none) | IAP + Workspace group | added |
| Streamlit editing (none) | Django admin, audit trail | added |

Two capabilities the prototype has that Django admin covers on the editor side
as well: the Data Explorer becomes admin list views, and the coverage drill-down
becomes admin inlines on the outlet form.

### Public vs. admin is a deployment switch, not a lost feature

The Coverage Records and Data Explorer tabs are built into the widget. Whether
the **public** embed exposes them is one config flag. Sizes if you do:

| Payload | Raw | Gzipped |
|---|---|---|
| Outlets only | 367KB | 65KB |
| Coverage only | 1.5MB | 138KB |
| Both | 1.9MB | 204KB |

All three are servable as static files, so exposing coverage publicly later is a
decision, not an architecture change.

### What genuinely does not carry over

Streamlit itself. It has no auth model, no per-row writes, no audit trail, and
reruns the whole script on every interaction — fine for one person exploring,
unworkable for a team editing shared data. Keep it locally against a read-only
connection if it is still useful for ad-hoc work; do not deploy it.
