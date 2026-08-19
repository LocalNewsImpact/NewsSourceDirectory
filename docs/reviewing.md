# Reviewing the registry

For the people cleaning the data, not the people building the software. It
assumes nothing about Django and nothing about the command line.

The registry is at <https://sources.localnewsimpact.org/admin/>. Sign in with a
`@localnewsimpact.org` Google account.

---

## What you are looking at

The registry was built by merging eight studies. Each study was a spreadsheet
listing outlets and the places they cover; together they hold **8,561 rows**,
which describe about **2,809 outlets**. The same paper appears in several
studies, under several spellings, so the rows had to be grouped.

Two record types matter:

**Coverage records** are the original spreadsheet rows. They are evidence and
they never change. Every one keeps the file and sheet it came from, so any value
in the registry can be traced back to the study that asserted it. The admin will
not let you edit them — that is deliberate, not a permissions mistake.

**Outlets** are what the registry publishes: one row per masthead, derived from
the coverage records underneath it. These are yours to correct.

An outlet groups coverage records by a rule: the website's domain, plus the
first part of the path where one host carries many outlets. It is right most of
the time and wrong in a way that needs a person the rest of the time. That
residue is the review queue.

---

## Where to start

The admin home page is a dashboard rather than a list of tables. The tiles are
ordered so the top row is the work:

| Tile | What it means |
|---|---|
| **Outlets needing review** | The rule grouped several different names together and could not tell whether that was right |
| **Place links to confirm** | An outlet was linked to a town by name rather than by identifier, so the match may be wrong |
| **No domain recorded** | No usable website, so the outlet was grouped by name and state instead |
| **No medium recorded** | The study did not say whether it is a newspaper, a station or online |

Each tile is a link into a filtered list. Work one tile at a time.

---

## The merge queue

An outlet is flagged when the coverage records grouped under it carry more than
one distinct name. The **distinct names in coverage** filter on the outlet list
offers "One — consistent" and "Two or more — suspected bad merge"; the second is
the queue.

Record count is not the signal and should not be read as one: an outlet
legitimately has hundreds of coverage rows when a study listed it once per
municipality.

Open the outlet. The coverage records appear underneath it, with the original
name, city, county and source file on each. That is the evidence for whether
this is one outlet or several.

Four things cause a flag, and they need different answers:

**Punctuation and spelling of the same paper.** "Record, The" and "The Record";
"Wayne County Journal-Banner" and "WayNe County Journal Banner". One outlet.
Correct the name to the form you want published and use **Mark reviewed**.

**A longer and a shorter form.** "Perryville Republic Monitor" and "Republic
Monitor". Still one outlet. Decide which is the masthead and set it.

**Two papers joined by a slash.** "Reynolds County Courier/Wayne County Journal
Banner", "The Daily/Dexter Statesman". These are two outlets recorded in one
cell. **Split** them, below.

**Genuinely different papers sharing a website.** A chain that puts several
mastheads on one domain. Also a split.

When the flag was wrong and the grouping is right, **Mark reviewed** and move on.
Clearing a flag is a decision worth recording, so say why in the review note
where it is not obvious.

---

## Split and Merge

These are the two actions that reshape data. Both are in the **Action** dropdown
at the top of the outlet list, and both apply to the outlets you tick.

### Split: one outlet per distinct name in coverage

Use it when one row is really several papers.

The original outlet keeps the name with the most coverage records behind it,
along with its identity, so anything already linked to it stays valid. Every
other name becomes a new outlet and takes its own coverage records with it. The
new outlets inherit the state, medium and owner of the original, are flagged for
review, and carry a note saying what they were split from.

**Nothing is deleted.** A split can be undone by merging the pieces back
together.

An outlet with only one name in its coverage is skipped rather than changed, so
selecting a whole page and splitting will not damage the rows that were fine.

### Merge: fold the selected outlets into the oldest

Use it when several rows are one paper — including to reassemble something you
split too far.

Select two or more. The oldest surviving outlet absorbs the others: their
coverage records and place links move onto it, and the emptied outlets are then
deleted. The survivor's counts are recalculated and a note records which outlets
went in.

**Coverage moves rather than being copied, so a merge loses no evidence** — but
the absorbed outlet rows themselves are gone. Merging the wrong two is undone by
splitting the result, not by an undo button.

Selecting one outlet does nothing except warn you.

---

## Place links

Places come from the USGS national names file. Where a study gave a place
identifier, the link is exact. Where it gave only a name, the link was matched on
the name and flagged, because two towns can share one.

The queue is under **Outlet places**, filtered to those needing review. Check
that the town is the one the outlet actually covers — the state and county on the
place are the things to compare — then use **Confirm: these places are
correct**. Confirming records that a person decided it, not a string match.

---

## Publishing

Nothing you change is public until the feed is published. The public directory
reads a static file, not the database.

**Publish the public feed now** is in the outlet list's Action dropdown. It
ignores which outlets you have ticked — the feed is always the whole registry.

It is a deliberate action rather than something that fires on every save, so
that a half-finished merge is not published as you go. Publishing takes a few
minutes. Finish a batch of review, then publish once.

Outlets marked **not published** are held back from the feed. Closed outlets are
published and marked as closed, because a paper that has shut is a fact worth
recording rather than a row to delete.

---

## What not to do

**Do not delete an outlet to get rid of a duplicate.** Merge it. Deleting throws
away the coverage records' link to their evidence.

**Do not edit a coverage record** to fix a name. The admin prevents it. The
spreadsheet row said what it said; the correction belongs on the outlet.

**Do not use the import buttons** on the outlet or coverage lists unless you
have agreed the file with whoever maintains the registry. Imports are how the
data got its current shape and a wrong one is laborious to unpick.

---

## When something looks wrong

Some of what is in the registry is wrong in the source data rather than in the
merge — a misspelled masthead, a paper attributed to the wrong town, a domain
that belongs to a different publisher. Those are worth recording even when you
cannot fix them: put what you found in the outlet's review note, leave it
flagged, and raise it as an issue on the repository so it is not lost when the
queue is next worked.
