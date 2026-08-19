"""Asking GitHub to publish the feed.

Curation happens in the database, which produces no git event, so the admin has
to say when something is worth publishing. It does that by firing a
`repository_dispatch`, which the publish workflow listens for.

The admin only *requests* a publish. It never writes the feed itself: the
workflow reads through a role that holds SELECT and nothing else, so the path
that produces public data cannot also change it.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

API = "https://api.github.com/repos/{repo}/dispatches"
DEFAULT_REPO = "LocalNewsImpact/NewsSourceDirectory"


class PublishError(Exception):
    """Raised when GitHub declines, so the admin can say what went wrong rather
    than reporting a success nobody can verify."""


def request_publish(reason: str = "admin") -> None:
    token = os.environ.get("GITHUB_DISPATCH_TOKEN", "").strip()
    if not token:
        raise PublishError(
            "No GITHUB_DISPATCH_TOKEN configured, so the feed cannot be "
            "requested from here. Run the workflow from the Actions tab."
        )

    repo = os.environ.get("GITHUB_REPO", DEFAULT_REPO)
    body = json.dumps({"event_type": "publish-feed", "client_payload": {"reason": reason}})

    request = urllib.request.Request(
        API.format(repo=repo),
        data=body.encode(),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            # GitHub answers 204 with no body when it accepts the dispatch.
            if response.status not in (200, 202, 204):
                raise PublishError(f"GitHub returned {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200]
        raise PublishError(f"GitHub returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise PublishError(f"could not reach GitHub: {exc.reason}") from exc

    logger.info("publish requested (%s)", reason)
