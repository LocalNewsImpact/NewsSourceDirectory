# Loading crawler sources into the registry

The news crawler (`mizzou-news-crawler`) keeps its own `sources` table: the sites
it fetches, with the operational state needed to fetch them. Some of that table
is editorial — name, city, county, owner, medium, state — and belongs in the
registry. This describes how to move it, what has to be normalized on the way,
and what has no home yet.

Written against the live data on 2026-08-19: 1,149 sources in four datasets, of
which the `Mizzou-Missouri-State` dataset is 188 rows. Counts below are that
dataset unless stated.

The crawler stays a separate system. This is a one-way load, registry ← crawler,
and nothing here gives the registry access to the crawler's database at runtime.

---

## 1. The shape of the load

Do not write into `Outlet` directly. Emit a CSV in the columns `import_source`
already accepts, and let the existing pipeline do the rest:

```
crawler sources ──► export.csv ──► import_source ──► CoverageRecord ──► rebuild_outlets ──► Outlet
```

Three reasons this is the right seam rather than a bespoke loader:

- **Provenance survives.** Every row keeps `source_file`, `source_sheet` and
  `legacy_outlet_id`, so a value in the registry can always be traced back to
  the crawler row it came from, exactly as the eight spreadsheet studies can.
- **The identity rule is applied once.** `rebuild_outlets` groups by
  `identity_key()`. A separate loader would have to reimplement it and would
  drift.
- **It is reversible.** Deleting the coverage rows for one `source_file` and
  rebuilding restores the previous state. A direct write to `Outlet` is not
  undoable.

The export is a read-only query against the crawler database. It should run as a
scheduled job with a read-only role, not from a laptop.

### Columns to emit

`import_source` recognises these; anything else in the file is ignored.

| CSV column | Value |
|---|---|
| `outlet_name_raw` | `sources.canonical_name` |
| `url` | `https://` + `sources.host` |
| `medium` | `sources.type`, after the vocabulary remap in §4 |
| `state` | `sources.metadata->>'state'` |
| `city` | `sources.city` |
| `county` | `sources.county` |
| `ownership` | `sources.owner` |
| `source_file` | `mizzou-news-crawler` |
| `source_sheet` | the dataset slug, e.g. `Mizzou-Missouri-State` |
| `outlet_id` | `sources.id` (the crawler UUID, kept as `legacy_outlet_id`) |
| `notes` | free text — see §6 for what to park here |

`rebuild_outlets` then rolls these up: `ownership` becomes an `Owner` row,
`medium` a `Medium` FK through `medium_slug()`, `state` a `State` FK through
`state_lookup_key()`, and `city`/`county` stay on the outlet.

---

## 2. Identity: what joins to what

The join key is the registrable domain, as everywhere else in this project.
Name and city cannot be the key — see the wire-misattribution work in the
crawler for why domain aliases defeat name matching.

**`host_norm` is not a registrable domain.** It is a lowercased host and it
keeps `www.`, so five pairs in this dataset are one outlet each:

```
the-standard.org      newspressnow.com     kansascity.com
stlamerican.com       audacy.com
```

Loading `host_norm` unchanged creates five duplicate outlets and five
`identity_key` collisions. Strip the leading `www.` before building the URL, or
let `registrable_domain()` do it.

**188 rows are 183 outlets.**

| | |
|---|---|
| Crawler rows in the dataset | 188 |
| Distinct registrable domains | 183 |
| Already an outlet in the registry | 26 |
| New to the registry | 157 |
| Registry Missouri outlets with no crawler source | 21 |

So this is overwhelmingly an insert. Only 26 rows are a merge, and those are the
ones that need review (§5).

**One ambiguous join.** `dailyjournalonline.com` is a single crawler source but
two registry outlets — Daily Journal, Park Hills and Farmington Press — because
the identity rule splits shared hosts on the first path segment and the crawler
has no path, only a host. Any host the registry has split this way cannot be
matched automatically. There is one today; there will be more as the crawler
takes on datasets that overlap the studies.

---

## 3. Field mapping

### Aligns directly

| Crawler | Registry | Filled | Note |
|---|---|---|---|
| `host_norm` | `Outlet.domain`, `identity_key` | 188/188 | strip `www.` first |
| `canonical_name` | `Outlet.name` | 188/188 | conflicts on merge, §5 |
| `city` | `Outlet.city` | 186/188 | |
| `county` | `Outlet.county` | 184/188 | strip a trailing "County" |
| `owner` | `Owner` via `ownership` | 152/188 | the largest gain, §7 |
| `type` | `Outlet.medium` | 158/188 | needs vocabulary work, §4 |
| `metadata->>'state'` | `Outlet.state` | 158/188 | JSON, not a column, §4 |

### Has a column but must not be mapped to it

`sources.status` is `active` (160), `retired` (25), `paused` (3). These are
crawler states — whether the fetcher should visit the site — not publication
states. `retired` means the crawler gave up on it, which is not the same claim
as `Outlet.status = closed`, and 25 outlets would be wrongly marked closed.

Carry it as a note if it is useful for triage, and let a human decide which
retirements are actual closures.

### No home in the registry

| Crawler | Filled | |
|---|---|---|
| `metadata->>'frequency'` | 182/188 | Real editorial attribute, well populated, no field. §6 |
| `metadata->>'address1'` / `address2` | 149 / 39 | Street address of the newsroom. §6 |
| `metadata->>'zip'` | 148/188 | §6 |
| `local_broadcaster_callsigns.callsign` | 23 of 30 broadcast | FCC callsign, a proper external identifier. §6 |

### Deliberately not carried

Everything else on `sources` is operational and stays in the crawler:
`bot_sensitivity`, `bot_protection_type`, `bot_encounters`, all RSS state,
`extraction_method`, `discovery_proxy`, `selenium_only`, `discovered_sections`,
`requires_login`, `auth_type`, `auth_secret_name`, `auth_config`, `paused_at`,
`paused_reason`.

`auth_secret_name` in particular names a credential. It must never appear in an
export that feeds a public directory.

---

## 4. Normalization

### `type` mixes medium with origin

The crawler's `type` describes both the delivery form and where the outlet was
born. The registry splits those: `Medium` is the form, `Category` the kind.

Values in this dataset:

```
print native     123      audio_broadcast   16      digital_native    4
(null)            30      video_broadcast   13      television        1
Print native       1
```

`MEDIUM_SLUGS` in `directory/vocabulary.py` already maps `digital native`. These
have to be added:

```python
"print native": "newspaper",
"audio_broadcast": "radio",
"video_broadcast": "television",
"digital_native": "online",      # the underscore spelling, alongside the space
```

Casing is already inconsistent in the source (`Print native` beside `print
native`), which `medium_slug()` handles by lowercasing.

Do **not** add `broadcast` (10 rows across other datasets). It does not say radio
or television, and guessing produces a wrong answer nobody sees. Leave it
unmapped so it lands in the curation queue.

`print native` → Newspaper is a lossy mapping: it asserts a form from a
statement about origin. It is right for these 124 rows, and the origin
distinction is worth keeping as a `Category` if it turns out to matter.

### `state` lives in a JSON blob

There is no `state` column on `sources`. It is `metadata->>'state'`, and across
the whole crawler it is present but **empty** on 896 of 1,149 rows — every VT
source, despite all of them being Vermont outlets. In this dataset it is filled
on 158 of 188, written as `MO` on 157 and `Missouri` on one.

`state_lookup_key()` already accepts both spellings. Nothing else is needed here,
but any load of the VT dataset must supply the state from the dataset rather than
the row.

### `frequency` casing

182 of 188, and dirty: `weekly` (78) beside `Weekly` (15), `monthly` beside
`Monthly`, plus `bi-weekly`, `Tri-weekly`, `semi weekly`, `weekly/daily`,
`continuous` and `Broadcast`. If §6 adds the field, it needs a controlled
vocabulary and a mapping table in `vocabulary.py`, in the same shape as
`MEDIUM_SLUGS`. `Broadcast` is not a frequency and should not map to one.

### `county`

Written both with and without the word "County" depending on the study. Strip a
trailing `County` before matching a `Place`, or the same county produces two
places.

---

## 5. Conflicts on the 26 merges

Of the 26 domains that already exist in the registry, **17 have a different
name**:

```
republicmonitor.com       'Perryville Republic Monitor'   'Republic Monitor'
waynecojournalbanner.com  'Reynolds County Courier/…'     'Wayne County Journal-Banner'
ksdk.com                  'KSDK NBC'                      'KSDK (Channel 5, NBC)'
dexterstatesman.com       'The Daily/Dexter Statesman'    'Dexter Statesman'
stljewishlight.org        'St. Louis Jewish Light'        'St. Lewis Jewish Light'
timesnewspapers.com       'Fayette Advertiser'            'Webster-Kirkwood Times'
```

These are four different situations and only a person can tell them apart: a
longer form of the same name, a slash-joined pair that is really two outlets, a
typo in the registry (`St. Lewis`), and a genuine disagreement about which outlet
owns the domain (`timesnewspapers.com`).

Medium is known on both sides for 21 of the 26: it agrees on 19 and disagrees on
2.

**The load must not overwrite curated values.** `rebuild_outlets` already
behaves correctly: an outlet that exists keeps every value an editor has set and
only blank fields are filled, unless `--force` is passed. `--force` is not
appropriate here.

That default is also what makes the load worth running — the owner arrives on the
outlets that have none without touching a name anyone has curated.
Every conflict should raise a `DataQualityIssue` so it appears on the admin
dashboard beside the existing merge queue, rather than being resolved silently in
either direction.

---

## 6. Schema changes this needs

Three, none of them structural:

**`Outlet.frequency`** — a `CharField` with a controlled vocabulary, plus
`frequency_raw` for the original string, following the pattern already used for
`founded` / `founded_raw`. 182 of 188 rows carry one and there is nowhere to put
it.

**Newsroom address** — `address1`, `address2`, `zip` on `Outlet`, or a small
related model if a mailing address is wanted separately from a physical one. Note
that a street address is a different assertion from the `Place` links: the
address is where the newsroom sits, the places are what it covers.

**Callsign** — 23 of the 30 broadcast outlets in this dataset have an FCC
callsign in the crawler's `local_broadcaster_callsigns` table, every one of them
linked to its source row. A callsign is a real external identifier and a better
key than a name. Worth a field on `Outlet` rather than a note. Seven broadcast
outlets have none, so the field has to be optional.

Until these exist, the values can be parked in `CoverageRecord.notes` so nothing
is lost, but they will not be queryable or published.

---

## 7. What the registry gains

Owner is the reason to do this. **Not one of the 51 Missouri outlets in the
registry has an owner; 152 of the 188 crawler rows do.** City and county are
close to complete on both sides, so the merge adds little there.

The other gain is coverage: 157 Missouri outlets the registry does not have at
all, against 51 it does.

---

## 8. Dataset membership

The crawler groups sources into datasets — `Mizzou-Missouri-State` (188),
`VT-Community-News` (901), `WSU-Washington-State` (36), `Penn-State-Lehigh` (0).
The registry's `Collection` model is the equivalent and needs no change: it is
already many-to-many, which matters because 5 of the 1,149 sources belong to two
datasets.

Map one dataset to one collection, and set `source_sheet` to the dataset slug so
the origin is visible on every coverage row.

---

## 9. Open questions

- **Cadence.** One-off backfill, or a scheduled re-export? A repeat load must be
  idempotent on `legacy_outlet_id`, and must not resurrect an outlet a curator
  deleted or re-merge one they split.
- **Direction of authority.** When the crawler and the registry disagree on a
  name after a curator has reviewed it, which wins on the next run? The
  conservative answer is the registry, with the crawler value raised as an issue.
- **The other three datasets.** VT is 901 sources with no state recorded on any
  row and 367 provisional names; it should not be loaded until those are fixed.
  WSU is 36 and clean. Lehigh is empty.
- **Whether the crawler should read back.** Out of scope here. If it happens, the
  join is the same normalized registrable domain, one way only.
