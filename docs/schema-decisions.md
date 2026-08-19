# Schema decisions

Four questions were open on `schema/models_draft.py`. Each is answered below
against the real data — all 8,561 coverage records — rather than by preference.

---

## 1. Is the identity rule right?

**Answer: close enough to build on, and the residue is the review queue.**

`schema/identity.py` implements it: host plus the first meaningful path segment,
two segments on hosts known to carry many outlets, and `name|state` when there is
no usable URL.

| | Outlets |
|---|---|
| Prototype (bare domain) | 2,103 |
| This rule | **2,809** |
| Distinct raw names (upper bound) | 3,205 |

167 identities still cover more than one raw name. Inspecting them, they are two
different things and no rule separates them:

- **Should merge** — `hometownsource.com/sun_sailor` holds "Minnetonka / Excelsior
  / Eden Prairie Sun Sailor" and "Minnetonka-Excelsior-Eden Prairie Sun Sailor".
  Same paper, different punctuation. The rule is right.
- **Should split** — `globegazette.com` holds both the *Britt News-Tribune* and
  the *Forest City Summit*; `pressofatlanticcity.com/currents_gazettes` holds
  eight distinct *Current of…* papers. The rule is wrong.

So 167 rows land in the review queue rather than being resolved automatically.
That is the correct outcome: a person can tell those two cases apart in seconds
and no heuristic can.

Three classes of source-data error were found and are handled explicitly:
placeholder URLs (`no website`), shared social hosts with no path, and Library of
Congress catalogue URLs recorded as if they were outlet homepages.

---

## 2. Do Medium and Category stay separate axes?

**Answer: yes — the data forces it.**

Every value in the `medium` column across both tables:

| Value | Count | Disposition |
|---|---|---|
| Newspaper | 4,834 | medium |
| Television | 1,388 | medium |
| Online | 1,230 | medium |
| Radio | 1,036 | medium |
| Magazine | 420 | medium |
| Public Broadcasting | 57 (+2 "Public Broadcast") | medium |
| **Ethnic Outlets** | 82 | **category** |
| **Network Sites** | 62 | **category** |
| Facebook page / group | 15 | Online, with a platform note |
| TV station, TV (NBC/CBS/Fox/Public) | 12 | Television |
| `Type`, two URLs, a call sign | 6 | junk — import errors |

"Ethnic Outlets" and "Network Sites" describe something orthogonal to medium: an
ethnic newspaper is still a newspaper. Keeping one column would force a choice
between recording that a title is a newspaper and recording that it serves an
ethnic community.

So: **six media** in a controlled vocabulary, **categories** as a separate
many-to-many, and the TV network (NBC/CBS/Fox) not modelled at all — twelve
records do not justify a field.

---

## 3. Is multi-state coverage real?

**Answer: real, but rare — so `Outlet.state` is a single foreign key.**

Under the prototype's dedupe, apparent multi-state outlets were merge damage:
"The Aiken Leader" spanned 11 states because 70 unrelated Facebook-only outlets
had been merged into it.

Under the corrected identity rule only **9 of 2,809** identities span more than
one state, and inspection separates them cleanly:

**Genuine** — broadcast markets and border towns:

| Outlet | States |
|---|---|
| La Crosse Tribune | Minnesota, Wisconsin |
| Bluffton Today | Georgia, South Carolina |
| WRDW CBS 12 | Georgia, South Carolina |
| KXLT / FOX 47 Rochester | Iowa, Minnesota |

**Still artefacts** — name variants or residual over-merges: `jacksonsun.com`
(two unrelated papers with similar names), `marionstar.com`, `953wiki.com`,
`wowktv.com`, `thejournalmessenger.com`.

Four genuine cases out of 2,809 does not justify a many-to-many on `Outlet`.
`Outlet.state` is the outlet's home state; the breadth of what it covers lives in
its coverage records, and the feed can derive a `coverage_states` list from them
without the schema carrying the ambiguity.

---

## 4. Which coverage fields roll up to Outlet?

**Answer: measured, not guessed.** For each field, how often does one outlet's
coverage records disagree?

| Field | Outlets with data | Disagree | Decision |
|---|---|---|---|
| `state` | 2,692 | 0.3% | roll up |
| `ownership` | 524 | 0.4% | roll up |
| `ownership_type` | 522 | 0% | roll up |
| `newsbank_availability` | 187 | 0% | roll up |
| `medium` | 2,658 | 1% | roll up |
| `closed_date` | 86 | 1% | roll up |
| `founded` | 388 | 2% | roll up |
| `notes` | 754 | 3% | roll up |
| `county` | 1,365 | 4% | roll up |
| `city` | 1,597 | **7%** | roll up as primary, keep the rest |
| `source_file` | 2,809 | 13% | stays — it *is* provenance |
| `domains_set_length` | 34 | 26% | stays |
| `article_length` | 34 | 26% | stays |
| `mun_id` / `gnis` | 575 | **37%** | stays |

The split is sharp. Descriptive attributes of the outlet barely vary and belong
on `Outlet`. The fields that vary are per-observation by nature: `mun_id` and
`gnis` identify which *municipality* a New Jersey record covers, and the Montana
measures are per-sample. Those are properties of the coverage row, not the
outlet, and flattening them would destroy information.

`city` at 7% is the honest middle: an outlet has a home city, and its coverage
often spans neighbouring ones. Roll up the primary and let coverage hold the rest.

---

## 5. Is geographic coverage first-class?

**Answer: yes — `Place` and `Outlet ↔ Place`.**

The New Jersey data already carries **4,480 assertions that a named outlet covers
a named municipality**, across 562 municipalities and 183 outlets. Median two
municipalities per outlet; one covers 663.

| Municipalities served by | Count |
|---|---|
| exactly 1 outlet | **27** |
| 2 | 7 |
| 3 | 21 |
| 4 | 14 |
| 5 or more | 305 |

Those 27 are the reason. A registry that stores this as provenance can show it
per record but cannot answer "which places are served by one outlet or none",
which is close to the point of the exercise.

`OutletPlace` is a through model rather than a plain many-to-many so each claim
keeps its source. Who asserted that an outlet covers Montclair is the difference
between a finding and an assumption. `gnis` is the join key — names collide
across states and within them.

---

## 6. Is ownership normalised?

**Answer: yes — an `Owner` table.**

832 records carry ownership across **281 distinct strings**: Adams Publishing
Group (102), Forum Communications (36), Townsquare Media (26), Lillie Suburban
(22). Chain consolidation is a core research subject, and a text field cannot
group "Townsquare Media, Inc" with "Townsquare Media Inc".

`Owner.parent` is self-referential, so a subsidiary can point at its group
without flattening the distinction — which matters when a chain acquires another
chain rather than a title. `ownership_type` moves onto `Owner`, since it
describes the owner rather than the outlet, and varies 0% within an outlet.

Import needs a one-time reconciliation of spelling variants, via `match_key`.

---

## 7. Do closed outlets publish?

**Answer: yes, clearly marked.**

79 outlets carry a closing date. A directory of local news that silently drops
closures hides exactly the phenomenon the consortium documents, so `status`
publishes alongside everything else and the widget can show or filter it.

The dates are inconsistent — `2016` beside `1/18/2019` and `10/5/2019` — so
`founded` and `closed_date` become real date fields, parsed where possible, with
`founded_raw` and `closed_date_raw` keeping the original either way. A value is
never discarded because it failed to parse.

---

## 8. Is succession modelled?

**Answer: not yet, and nothing forecloses it.**

`django-simple-history` already records a rename, so the trail exists.
`Status.MERGED` marks the outcome without asserting a structure. A
predecessor/successor link can be added when there is a real case to hang it on,
rather than a hypothetical one.

---

## 9. Where does `Place` come from?

**Answer: seeded from GNIS, not from the coverage data.**

Building `Place` only from places the data mentions can never answer the question
that matters. A municipality with no outlet has no coverage record, so it cannot
appear in a table derived from coverage records. Seeding from the USGS Domestic
Names National File turns "27 municipalities are served by one outlet" into "and
N more are served by none".

Three things the source data forces:

1. **GNIS ids arrive as floats.** The values are real feature ids — 546 of six
   digits, 15 of seven — but stored as `"1723212.0"`. They need coercing to
   integers on import or they will never match the gazetteer.
2. **`gnis` and `mun_id` do not agree.** 561 distinct GNIS values and 562
   distinct `mun_id` values produce **597 distinct pairs**, so roughly 36
   disagree. Both are kept and the disagreements go to review; neither is assumed
   correct.
3. **Only New Jersey has GNIS ids at all** — all 4,480 of its rows, and none
   elsewhere. Every other state carries city and county names only.

That third point is why `OutletPlace.match_method` exists. A link resolved from a
GNIS id in the source is a fact; a link resolved by matching "Springfield" against
a gazetteer is an inference, and the two should not be indistinguishable once
they are in the database. Name-matched links default to `needs_review`.

---

## Deferred

- **Researcher portal** — held. Nothing in the schema forecloses it.
- **Succession** — see above.
- **Feed destination** — settled: an S3 bucket, on its own subdomain.

---

## 10. What GNIS actually contains

Checked against the real 37MB national file rather than assumed, after an
earlier version of `seed_places` was written against invented column names and
its tests validated the invention.

**The file.** 981,698 rows, of which 256,114 are `Populated Place` or `Civil`.
The header is lowercase and carries a BOM. There is **no state abbreviation
column** — state arrives as `state_name` plus `state_numeric`, the FIPS code.

**`Civil` cannot be filtered out.** It means different things by state: New
Jersey municipalities are Civil features, while in Missouri the same class is
largely land surveys and planning regions. Of the 511 GNIS ids in the coverage
data that resolve at all, **506 are Civil**. Dropping the class would break every
real link we have, so `feature_class` is stored on the row rather than collapsed.

### Identity joins to attributes

GNIS carries no Census GEOID, but the Census Gazetteer keys on `ANSICODE`, which
**is** the GNIS feature id — so the join is exact rather than a name match.
Tested against the real coverage ids:

| Route | Joined |
|---|---|
| Census places file | 290 |
| Census county subdivisions file | 505 |
| **Either** | **505 of 561 — 90%** |

Two files are needed: New Jersey is mostly townships, which are county
subdivisions rather than places. `Place.census_geoid` exists to hold the result
whenever attributes are wanted; nothing populates it yet.

The remaining 10% are faults in the source: 50 ids absent from GNIS entirely,
and 5 naming a reservoir, two summits, a spring and a stream.

### Reading the coverage figures

Seeding the national file gives 256,114 places, and linking the coverage data
gives 4,341 exact GNIS links and 2,891 name matches. The tempting headline from
that — *2,467 New Jersey places have no outlet* — is wrong by roughly eighty
times, and the reason is the feature class:

| New Jersey | Total | Served | None |
|---|---|---|---|
| `Civil` — municipalities | 574 | 543 | **31** |
| `Populated Place` — hamlets, neighbourhoods | 2,436 | 0 | 2,436 |

The 2,436 could never link: the New Jersey study recorded coverage at
municipality level, so unincorporated hamlets have no coverage record by
construction, not by absence of news. **31 of 574 municipalities** is the figure
that means something.

Any question of the form "how many places have no outlet" has to name a feature
class, or it is measuring the gazetteer rather than the news ecosystem.
