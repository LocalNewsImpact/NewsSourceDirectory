"""Mapping the source's free text onto the controlled vocabularies.

The source holds 18 distinct values in a column meant for six, plus states
written both as codes and names. Every mapping here is derived from counting the
real data — see docs/schema-decisions.md.

Anything unmapped returns None rather than guessing. An outlet with no medium is
a curation task; an outlet with the wrong medium is a wrong answer nobody sees.
"""

from __future__ import annotations

import re
from datetime import date

# Free text -> Medium.slug. Television variants fold together: the network
# (NBC, CBS, Fox) appears on twelve records and does not justify a field.
MEDIUM_SLUGS = {
    "newspaper": "newspaper",
    "television": "television",
    "tv station": "television",
    "tv (nbc)": "television",
    "tv (cbs)": "television",
    "tv (fox)": "television",
    "tv (public)": "television",
    "radio": "radio",
    "online": "online",
    "digital native": "online",
    "digital-first (online)": "online",
    "facebook page": "online",
    "facebook group": "online",
    "magazine": "magazine",
    "public broadcasting": "public-broadcasting",
    "public broadcast": "public-broadcasting",
}

# Values in the medium column that describe something else entirely.
CATEGORY_SLUGS = {
    "ethnic outlets": "ethnic",
    "ethnic outlet": "ethnic",
    "network sites": "network-site",
    "network site": "network-site",
}

# Column headers that were imported as data by a mis-parsed spreadsheet.
HEADER_JUNK = {"type", "state", "outlet name", "url", "medium", "city", "county"}

_URLISH = re.compile(r"^(https?://|www\.)", re.I)


def medium_slug(raw: str) -> str | None:
    value = (raw or "").strip().lower()
    if not value or value in HEADER_JUNK or _URLISH.match(value):
        return None
    return MEDIUM_SLUGS.get(value)


def category_slug(raw: str) -> str | None:
    return CATEGORY_SLUGS.get((raw or "").strip().lower())


def state_lookup_key(raw: str) -> tuple[str, str] | None:
    """Return ('code'|'name', value) for a state written either way.

    The source mixes 'MS' with 'Mississippi', and admitted a literal 'State'
    from a header row.
    """
    value = (raw or "").strip()
    if not value or value.lower() in HEADER_JUNK:
        return None
    # Some rows carry "Missoula, MT" — the state is the trailing code.
    if "," in value:
        tail = value.rsplit(",", 1)[1].strip()
        if len(tail) == 2 and tail.isalpha():
            return ("code", tail.upper())
    if len(value) == 2 and value.isalpha():
        return ("code", value.upper())
    return ("name", value)


# Formats seen in the source: bare years alongside US-style dates.
DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d %B %Y", "%B %d, %Y")


def parse_date(raw: str) -> date | None:
    """Parse what can be parsed; the caller keeps the original either way.

    A bare year becomes 1 January, which is a convention rather than a fact —
    hence founded_raw and closed_date_raw, so nothing pretends to a precision
    the source did not have.
    """
    from datetime import datetime

    value = (raw or "").strip()
    if not value:
        return None

    if re.fullmatch(r"(19|20)\d{2}", value):
        return date(int(value), 1, 1)

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def owner_match_key(name: str) -> str:
    """Casefolded, punctuation-stripped, with corporate suffixes removed, so
    'Townsquare Media, Inc' groups with 'Townsquare Media Inc'."""
    value = (name or "").lower()
    value = re.sub(r"[.,]", " ", value)
    value = re.sub(r"\b(inc|llc|ltd|co|corp|corporation|company|group|holdings)\b", " ", value)
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")
