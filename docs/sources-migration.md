# Moving the crawler's source records into the registry

`docs/crawler-etl.md` describes a one-way load: crawler → registry, run once,
with the crawler keeping its own `sources` table as the record it works from.
This describes the next step, which reverses the direction of authority. The
registry becomes the place descriptive data about a publication is written, and
the crawler reads it.

Scope is descriptive data only — what a publication is. Nothing the crawler
observes about fetching a site moves. Records stay keyed on the UUIDs already
shared across the suite; no key is regenerated at any point.

Measured against production on 2026-09-04: `mizzou.sources` holds 1,149 rows,
`datadesk.directory.directory_outlet` holds 2,666 rows with a domain. Counts
below are from those two queries unless stated.

---

## 1. What the data shows

Five measurements determine the shape of the work.

| Measurement | Value |
| --- | ---: |
| Rows in `sources` | 1,149 |
| Distinct hosts after normalizing `www.` | 1,138 |
| Crawler hosts matching a registry outlet by domain | 66 |
| Crawler hosts with no outlet | 1,072 |
| Raw-SQL references to `sources` in `MizzouNewsCrawler/src` | 83 |
| Tables with a foreign key to `sources` | 5 |

Every `sources.id` is already UUID-shaped, stored as `character varying`.
`host_norm` is unique across all 1,149 rows.

### 1.1 The work is mostly record creation

94% of crawler hosts have no outlet in the registry. Rewiring the crawler's
reads is a smaller task than creating and reviewing the 1,072 outlets those
hosts imply.

### 1.2 The two databases cannot be joined

The crawler is the `mizzou` database. The registry is the `directory` schema of
the `datadesk` database. They share a Cloud SQL instance but are separate
databases, and Postgres does not join across databases.

Eighty-three raw-SQL sites join `sources` to `candidate_links`, `articles`,
`gazetteer` and `dataset_sources`, spread across twelve modules — `discovery.py`
(14), `source_processing.py` (7), `bot_sensitivity_manager.py` (6) and nine
others. Those joins have to stay inside one database.

This rules out the crawler querying the registry per row. Discovery and
extraction run as Argo workflows over thousands of rows; a network call in that
path is not viable, and it would not restore the joins in any case.

The registry publishes a read-only projection into the crawler's database. The
crawler joins the projection exactly as it joins `sources` today.

### 1.3 A source is not an outlet

The crawler stores one row per host, unique on `host_norm`. The registry
identifies an outlet by `identity_key()` — host plus the first meaningful path
segment, or name scoped by state where there is no website — so one domain can
carry several outlets, and an outlet can exist with no domain at all.

Consequences in the current data:

- 11 crawler rows collapse when `www.` is normalized away.
- Some hosts are subdomains (`270stories.mymurraystate.com`).
- At least one host is a bare IP address (`75.2.70.176`).

The relationship is many hosts to one outlet. It needs a table.

---

## 2. Which columns move

`sources` has 44 columns. The division is by writer: a column the crawler writes
during a run stays; a column a person would write about the publication moves.

### 2.1 Moves to the registry

| Column | Note |
| --- | --- |
| `canonical_name` | 1,147 of 1,149 populated |
| `city`, `county` | 1,147 populated |
| `owner` | 1,148 populated; free text, normalizes to `Owner` |
| `type` | 1,146 populated; maps to `Medium` vocabulary |
| `host`, `host_norm` | Copied to `OutletHost`, retained on `sources` (§2.4) |
| `has_paywall`, `subscription_cost`, `subscription_period`, `login_url` | Added by PR #483; reviewed by people in Datadesk |
| `requires_login` | Property of the publication, not of the fetch |
| `local_broadcaster_callsigns` | Separate table, moves whole |

From `metadata`: `state` (1,143 rows), `frequency` (1,132), `address1` (1,090),
`address2` (1,090), `zip` (1,090), `media_type` (932), `cohort` (932),
`name_is_provisional` (896), `name_source` (896).

### 2.2 Stays with the crawler

Bot detection: `bot_sensitivity`, `bot_sensitivity_updated_at`,
`bot_encounters`, `last_bot_detection_at`, `bot_detection_metadata`,
`bot_protection_type`, `bot_protection_detected_at`, `selenium_only`.

RSS: `rss_feeds`, `rss_consecutive_failures`, `rss_transient_failures`,
`rss_missing_at`, `rss_last_failed_at`, `last_successful_rss_at`,
`skip_rss_until`.

Fetch strategy and state: `status`, `paused_at`, `paused_reason`,
`extraction_method`, `discovery_proxy`, `last_successful_method`,
`no_effective_methods_consecutive`, `no_effective_methods_last_seen`,
`amp_supported`, `discovered_sections`, `section_discovery_enabled`,
`section_last_updated`.

Authentication: `auth_type`, `auth_secret_name`, `auth_config`. These describe
how the crawler signs in; `auth_secret_name` is a Secret Manager pointer. No
credential is stored in either database and none moves.

### 2.3 `metadata` is split, not moved

`sources.metadata` carries descriptive keys and operational keys in the same
JSON column. The crawler writes `rss_consecutive_failures`,
`no_effective_methods_consecutive`, `last_successful_method`,
`last_discovery_at`, `cached_institutions` and `cached_landmarks` into it during
normal runs.

Moving the column whole would give the registry a field the crawler continues to
write. The descriptive keys listed in §2.1 are extracted to registry columns;
the operational keys stay in `sources.metadata`.

### 2.4 `host_norm` stays on `sources`

The crawler addresses sites by host. `host` and `host_norm` are copied to
`OutletHost` and retained on `sources`, because the projection is keyed on
`host_norm` and the crawler's own fetch path needs it without a join.

---

## 3. Registry schema additions

All additive. No existing field changes shape.

| Addition | Shape | Reason |
| --- | --- | --- |
| `OutletHost` | `outlet` FK, `host`, `host_norm` unique, `is_primary`, `legacy_source_id` | Resolves a crawler host to an outlet, and records the many-hosts-to-one-outlet relationship. `legacy_source_id` holds the crawler's existing UUID. |
| Contact fields | `address1`, `address2`, `zip`, `frequency` on `Outlet` | 1,090–1,132 crawler rows carry these in `metadata` and have nowhere else to go. |
| Paywall fields | `has_paywall`, `subscription_cost`, `subscription_period`, `login_url`, `requires_login` on `Outlet` | Datadesk's paywall review page writes these today. |
| `callsign` | On `OutletHost` | Broadcasters. The registry models Television and Radio as media with no field for a call sign. |
| Name provenance | `name_is_provisional`, `name_source` on `Outlet` | 896 crawler rows record a provisional name. `needs_review` records that a record needs attention but not why. |

`OutletPlace` and `CoverageRecord` are unchanged. `identity_key()` is unchanged.

---

## 4. Phases

Ordered by dependency. Each phase's exit gate is the next phase's precondition.
Phases 0–2 change no crawler behaviour.

### Phase 0 — Fix the contract

No schema or behaviour change.

- Add the source and outlet shapes to `lnic-contracts` alongside the existing
  review-note contract, recording which system owns each field.
- Commit the reconciliation report as a script: for every crawler host, its
  normalized form, its candidate outlet matches, and the reason for each match
  or miss. It runs repeatedly through phases 1–2 and is the evidence the
  migration is complete.

Exit gate: both repositories install the same contract version; the
reconciliation report runs in CI against a fixture.

### Phase 1 — Registry schema

Migrations for §3, with admin forms and validation. Nothing populates the new
fields.

Ship separately from any data change.

Exit gate: registry deployed, fields present and empty, existing pages
unchanged, the static feed build produces an unchanged manifest hash.

### Phase 2 — Identity reconciliation

The 1,072 unmatched hosts, in three populations:

1. **66 exact domain matches.** Linked automatically, then a sample reviewed. A
   matching domain is not proof of the same publication.
2. **Near matches.** `www.` variants, subdomains, and name-plus-state matches
   against outlets with no website. These go to the review queue rather than
   being decided by a script.
3. **The remainder.** An outlet is created from the crawler row, marked
   `needs_review`, with `name_source` recording the crawler as the origin and
   `name_is_provisional` carried across for the 896 rows that assert it.

Loading uses the existing seam described in `docs/crawler-etl.md`:
CSV → `import_source` → `CoverageRecord` → `rebuild_outlets`. Provenance
survives, `identity_key()` is applied once, and deleting the coverage rows for
one `source_file` and rebuilding reverses the load.

Every link is written to `OutletHost` with the crawler's UUID in
`legacy_source_id`.

Exit gate: all 1,149 sources resolve to exactly one outlet; the reconciliation
report shows zero unmatched and zero ambiguous. Ambiguity is resolved by a
person.

### Phase 3 — Projection

A registry job writes `directory_outlet_projection` into the `mizzou` database:
outlet UUID, `host_norm`, `contract_version`, `refreshed_at`, and the
descriptive columns. Refreshed on a schedule and on demand after an edit. The
crawler's role has SELECT on it and nothing else.

`sources` gains `outlet_id`, populated from phase 2.

Both copies of every descriptive value now exist. A comparison job reports rows
where they disagree.

Exit gate: the comparison job reports zero disagreements for seven consecutive
days spanning a full crawl cycle; refresh completes inside its schedule window.

### Phase 4 — Cut over the crawler's reads

Five deploys, in ascending order of consequence. Each is independently
revertible.

| Order | Field group | Sites | Consequence of an error |
| --- | --- | ---: | --- |
| 1 | `canonical_name` | 10 | Display only |
| 2 | `type` | 17 | Discovery strategy selection |
| 3 | `city`, `county`, `state` | 34 | Gazetteer matching and every geographic label |
| 4 | `owner` | 2 | Ownership analysis; registry `Owner` is normalized |
| 5 | Paywall fields | — | Moves with phase 6 |

Exit gate, per group: the gazetteer build produces identical output before and
after, and a discovery run over one dataset selects the same sources.

### Phase 5 — Single writer, then drop

1. Revoke UPDATE on the descriptive columns from the crawler's role. Run a
   release against that state. A permission error is loud and attributable; a
   column written in two places is not.
2. Export pre-drop values to GCS.
3. Drop the columns, in a migration containing no code change.

`host` and `host_norm` are retained (§2.4).

Exit gate: a full pipeline run — discovery through enrichment through export —
completes with the columns dropped.

### Phase 6 — Datadesk

Datadesk reads `sources` through unmanaged models and writes to it from the
paywall review page. Those writes become registry writes. Datadesk already
installs the registry as an app under `SERVICE_ROLE=sources`; what changes is
the alias the write is routed to.

The review queue's publisher column becomes a link to the registry record.

Exit gate: an edit in the registry changes what the crawler resolves within one
projection refresh, demonstrated end to end.

---

## 5. Keeping the schemas in step

Three services will share these tables. The failure to design against is a
column changing in one repository while the others' tests stay green.

**The contract package is the definition.** `lnic-contracts` carries the
projection's field names, types and ownership. A schema change starts as a
contract release; consumers pin a tag.

**Each app verifies its models against the live schema.** Datadesk has
`check_crawler_schema`, which compares its unmanaged models to the crawler's
`information_schema`; it reported two type mismatches on its first run. The
crawler and the registry get the same command against the projection. All three
run on a schedule, not only at deploy: drift arrives when another repository
deploys, which is not an event this one observes.

**The projection is versioned.** `contract_version` is written with each
refresh. The refresh job refuses to write a version the consumer does not
declare support for, and the consumer refuses to read one it does not
recognize. A mismatch stops the refresh with a named error.

None of this covers a dependency present in one environment and absent in
another. `/review/queue/` returned 500 on 2026-09-03 because a package was in
`requirements-dev.txt` and not `requirements.txt` — invisible to every test,
because the test environment installs the dev file. The mitigation is the
deploy-time import check in `smoke_queries`, not a test.

---

## 6. Tests

Both repositories run their suites against Postgres. The crawler always has;
Datadesk since 2026-09-03.

| Level | Assertion | Location |
| --- | --- | --- |
| Contract | Every consumer builds and reads the projection shape it declares; an unknown `contract_version` is refused rather than guessed | `lnic-contracts`, plus a conformance test in each consumer |
| Identity | Normalization is total and stable across `www.` variants, subdomains, bare IPs, outlets with no website, and two hosts that are one publication. Property-based over the real 1,138 hosts | registry |
| Projection | A registry edit reaches the crawler within one refresh; a deleted outlet does not orphan a source; a failed refresh leaves the previous projection intact | registry and crawler |
| Equivalence | For every source, the value read from the projection equals the value in the column it replaces. Runs against production data | crawler, as a management command |
| Pipeline | Gazetteer output is identical across each cut-over; a discovery run selects the same sources; enrichment's geographic labels do not move | crawler |
| Schema | Each app's models match the live schema it reads | all three, scheduled and pre-deploy |

---

## 7. Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Wrong identity match: two hosts merged into one outlet, or one publication split across two. A wrong city changes gazetteer matching and every downstream geographic label | High | No automatic match beyond exact domain equality; everything else goes to the review queue. The equivalence test runs against production data before any column is dropped. Gazetteer output must be identical |
| A cross-database join is written and works locally against one database | High | The projection lives in the crawler's database, so the local join remains possible. A test asserts no query crosses the alias boundary; the router refuses it in code |
| Stale projection: a correction does not reach the crawler, or the refresh stops unnoticed | Medium | `refreshed_at` on the projection; a staleness check fails past its threshold. Refresh is on-demand after an edit as well as scheduled |
| Two writers during phases 3–5: a registry edit is overwritten on the next crawl | Medium | The comparison job reports disagreement daily; UPDATE is revoked at the database level before columns are dropped |
| Crawl interruption mid-migration | Medium | One field group per deploy, each revertible. Begin while the crons are suspended |
| Editorial review of 1,072 new outlets does not finish | Medium | Phase 2 creates every outlet immediately, flagged `needs_review`. Review improves records; it does not gate the cut-over. Only ambiguous matches block, and those are counted |
| Schema drift across three repositories | Medium | Contract package, scheduled schema checks, versioned projection (§5) |
| Data with no home: frequency, addresses, ZIP, call signs | Low | Phase 1 adds the fields before phase 2 moves anything; phase 5 exports pre-drop values regardless |
| UUID churn breaking articles, gazetteer rows and BigQuery exports | Low | No source UUID is regenerated. `OutletHost.legacy_source_id` holds the existing one; the crawler's foreign keys do not change. Asserted in the test suite rather than assumed |

---

## 8. Open questions

These change the plan rather than fill it in, and should be settled before
phase 1.

1. **Does an outlet with several hosts stay one outlet?** `identity_key()` can
   treat a domain plus a path segment as separate outlets; the crawler treats
   each host separately. If a section subdomain folds into its parent
   publication, gazetteer counts and CIN totals move with it.
2. **Who owns `type`?** The crawler's free-text `type` and the registry's
   six-value `Medium` vocabulary are not the same field. The mapping is
   mechanical for most rows; the residue needs a decision.
3. **Does the registry's `status` govern crawling?** Both systems have a
   `status` column with different meanings — editorial (published, closed)
   against operational (active, paused). They must not be conflated, and one may
   need renaming.
4. **Is the projection refresh push or pull?** A registry job writing into the
   crawler database needs a role there. A crawler job reading the registry needs
   the reverse. The first keeps the crawler's permissions narrow; the second
   keeps the registry from holding credentials it otherwise would not.

---

## Sources for the figures

- `mizzou.sources`, `mizzou.information_schema.columns`, 2026-09-04.
- `datadesk.directory.directory_outlet`, 2026-09-04.
- Reference counts from `MizzouNewsCrawler/src` at `7b17d8ff`.
- `docs/crawler-etl.md` for the load path and the identity rule.
