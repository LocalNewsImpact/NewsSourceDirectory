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
