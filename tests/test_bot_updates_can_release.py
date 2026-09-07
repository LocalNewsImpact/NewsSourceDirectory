"""A dependency update can reach production without a person editing it.

Datadesk installs the newest tag of this repository, so a merge that
ships code must carry a new version: `tag-a-release.yml` refuses it
otherwise and `tests/test_release.py` fails the pull request first. Both
are right. Neither is something a bot can satisfy -- Renovate edits
requirements.txt and knows nothing about the version line -- so every
dependency pull request opened here failed the release guard and sat
there. Two were open when this was written, both red for that reason and
nothing else.

The bump a person would make by hand is made by a workflow instead.
These read its text rather than running it, because a workflow that does
the wrong thing on a bot's branch is discovered when the branch is
already wrong.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/bump-the-version-for-a-bot.yml"
TEXT = WORKFLOW.read_text()
PARSED = yaml.safe_load(TEXT)
# `on` is YAML 1.1's boolean true, which is why this is not PARSED["on"].
TRIGGERS = PARSED[True]


def test_it_runs_on_a_pull_request_being_updated():
    """Renovate force-pushes its branches, and the version must be right
    on the branch as it stands, not as it was opened."""
    assert set(TRIGGERS["pull_request"]["types"]) == {
        "opened",
        "synchronize",
        "reopened",
    }


def test_it_can_write():
    """Without contents: write the push is refused and the pull request
    stays red -- the failure this exists to remove."""
    assert PARSED["permissions"]["contents"] == "write"


def test_only_renovate():
    """Not `github.actor != 'someone'`. A workflow that pushes commits
    to a branch runs on the narrowest condition that does the job."""
    assert PARSED["jobs"]["bump"]["if"] == "github.actor == 'renovate[bot]'"


def test_it_reads_the_version_the_way_the_release_does():
    """Two readings of one line that must agree. tag-a-release.yml greps
    it; a TOML parser here would differ on the day the file changes
    shape, and the release is the one that decides."""
    release = (ROOT / ".github/workflows/tag-a-release.yml").read_text()
    grep = "grep -m1 '^version = ' pyproject.toml | cut -d'\"' -f2"
    assert grep in release
    assert grep in TEXT


def test_it_walks_the_patch_digit_only():
    """A dependency update changes what is installed, never what this
    package promises. Minor and major are decisions, and a decision has
    an author."""
    assert 'printf "%s.%s.%d", $1, $2, $3 + 1' in TEXT


def test_it_stops_when_the_version_is_already_free():
    """The push re-triggers this on `synchronize`. Without an early
    exit the workflow bumps again on its own commit, for ever."""
    assert 'if [ "$CURRENT" = "$VERSION" ]; then' in TEXT
    assert "exit 0" in TEXT


def test_it_does_not_rewrite_a_dependency_pin():
    """`version = ` appears once at the start of a line in this file, but
    the replace is anchored to the first match regardless."""
    assert "0,/^version = /s|^version = .*|" in TEXT
    assert len(re.findall(r"^version = ", (ROOT / "pyproject.toml").read_text(), re.M)) == 1


def test_no_heredoc_terminator_is_indented():
    """An indented terminator does not end a heredoc, and the shell then
    swallows the rest of the step. That defect once left a job in this
    suite reporting success in zero seconds without running."""
    for opener in re.finditer(r"<<-?'?(\w+)'?", TEXT):
        word = opener.group(1)
        assert re.search(rf"^{word}$", TEXT, re.M), f"{word} is never terminated at column 0"


def test_documentation_needs_no_version():
    """The same exemption tag-a-release.yml makes, or every docs pull
    request from a bot gets a pointless version bump."""
    assert TRIGGERS["pull_request"]["paths-ignore"] == ["**.md", "docs/**"]


def test_dependabot_is_gone():
    """A workflow triggered by Dependabot gets a read-only token whatever
    the permissions block says, so this could not push to its branches.
    The suite's updates come from Renovate instead, configured once in
    lnic-contracts."""
    assert not (ROOT / ".github/dependabot.yml").exists()
    renovate = ROOT / "renovate.json"
    assert renovate.exists()
    import json

    assert json.loads(renovate.read_text())["extends"] == ["local>LocalNewsImpact/lnic-contracts"]
