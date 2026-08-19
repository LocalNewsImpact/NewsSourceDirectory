"""Outlet identity.

The prototype keyed outlets on the bare registrable domain, which merged 1,102
distinct outlets into 222 rows — patch.com alone collapsed 134. Domain is a good
join hint and a poor identity: network publishers share one.

This rule was developed against all 8,561 coverage records and yields 2,809
identities where the prototype claimed 2,103. It is not perfect and is not meant
to be: 167 identities still cover more than one raw name, and inspection shows
those are a mix of genuine punctuation variants that *should* merge
("Minnetonka / Excelsior Sun Sailor" vs "Minnetonka-Excelsior Sun Sailor") and
genuine over-merges that should split (globegazette.com carrying both the Britt
News-Tribune and the Forest City Summit). No rule separates those; a person does.
The rule's job is to get the count roughly right and flag the rest for review.
"""

from __future__ import annotations

import re

# Path segments that do not distinguish one outlet from another.
GENERIC_SEGMENTS = frozenset({"", "news", "home", "index", "index.html", "local", "local-news"})

# Values that mean "no URL". The prototype treated "no website" as a domain and
# merged 103 unrelated outlets under it.
PLACEHOLDERS = frozenset(
    {"", "no website", "(no website)", "none", "n/a", "na", "-", "/", "unknown", "tbd"}
)

# Hosts where the path identifies the outlet, not the host. Each of these was
# found over-merging in the real data.
SHARED_HOSTS = frozenset(
    {
        "facebook.com",
        "m.facebook.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "patch.com",
        "tapinto.net",
        "axios.com",
        "dailyvoice.com",
        "hometownsource.com",
        "centraljersey.com",
        "mypaperonline.com",
        "rennamedia.com",
        "bizjournals.com",
    }
)

# Hosts that are never an outlet's own site. Library of Congress catalogue URLs
# appear in the source data as if they were homepages.
NOT_AN_OUTLET = frozenset({"loc.gov", "google.com", "wikipedia.org", "en.wikipedia.org"})

_SCHEME = re.compile(r"^https?://", re.I)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    return _NON_ALNUM.sub("-", (value or "").lower()).strip("-")


def registrable_domain(url: str) -> str:
    """Lowercased host, no scheme, no www., no port. The crawler join key."""
    host = _SCHEME.sub("", (url or "").strip()).lower()
    host = re.sub(r"^www\.", "", host).partition("/")[0]
    return host.split(":")[0].split("?")[0]


def identity_key(url: str, name: str, state: str = "") -> str:
    """A stable key for one outlet.

    With a usable URL: host plus the first meaningful path segment, or the first
    two segments on a host known to carry many outlets.

    Without one: the name scoped by state. Absence of a website must never itself
    become an identity, or every outlet lacking a URL merges into one.
    """
    fallback = f"name:{slugify(name)}|{slugify(state)}" if (name or "").strip() else ""

    url = (url or "").strip()
    if url.lower() in PLACEHOLDERS:
        return fallback

    host = registrable_domain(url)
    if not host or host in PLACEHOLDERS or host in NOT_AN_OUTLET:
        return fallback

    path = _SCHEME.sub("", url).partition("/")[2]
    segments = [s for s in path.split("?")[0].split("#")[0].split("/") if s]

    if host in SHARED_HOSTS:
        # The host alone says nothing here, so a pathless URL is no better than none.
        return f"{host}/{'/'.join(segments[:2])}" if segments else fallback

    first = segments[0] if segments else ""
    return host if first in GENERIC_SEGMENTS else f"{host}/{first}"
