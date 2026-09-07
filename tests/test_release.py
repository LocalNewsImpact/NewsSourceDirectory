"""How a merge here reaches production.

This package installs into Datadesk's image, resolved at build time to the
newest release tag of this repository. There is no pin to bump, so an
untagged merge is code that never ships -- and nothing says so: CI is green,
main is ahead, and production keeps serving the last tag. These assert the
workflow that closes that gap.
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/tag-a-release.yml"


def _spec():
    return yaml.safe_load(WORKFLOW.read_text())


def test_the_version_in_pyproject_is_what_gets_tagged():
    """One source for the number. A tag made by hand drifts from it -- v0.2.0
    was cut from a commit whose pyproject still said 0.1.0, so the package
    installed as v0.2.0 reported a different version than its tag."""
    text = WORKFLOW.read_text()
    assert "pyproject.toml" in text
    assert 'git tag -a "v$VERSION"' in text


def test_an_unbumped_version_fails_rather_than_shipping_nothing():
    """The failure this exists for is silent. Without the check the merge is
    green, the tag is not moved, and production serves the previous release
    while main looks deployed."""
    text = WORKFLOW.read_text()
    assert 'git rev-parse "v$VERSION"' in text
    assert "already tagged" in text
    assert "exit 1" in text


def test_the_tag_asks_datadesk_to_deploy():
    """A tag nothing acts on waits for Datadesk to deploy for its own
    reasons. That was the gap: releasing here changed nothing until something
    unrelated happened there."""
    text = WORKFLOW.read_text()
    assert "gh workflow run deploy.yml -R LocalNewsImpact/datadesk" in text


def test_a_missing_token_is_an_error_not_a_silent_skip():
    """The tag is pushed by the step before. If the deploy call is skipped
    quietly, the release exists and never ships -- the exact failure this
    workflow was written to remove."""
    text = WORKFLOW.read_text()
    assert 'if [ -z "$GH_TOKEN" ]' in text
    assert "DATADESK_DEPLOY_TOKEN is not set" in text


def test_documentation_does_not_cut_a_release():
    spec = _spec()
    ignored = spec[True]["push"]["paths-ignore"]
    assert "**.md" in ignored
    assert "docs/**" in ignored


def test_releases_do_not_run_concurrently():
    """Two merges in quick succession would race to tag and to fire the same
    deploy."""
    spec = _spec()
    assert spec["concurrency"]["group"] == "release-main"
    assert spec["concurrency"]["cancel-in-progress"] is False


def test_the_workflow_may_write_tags():
    spec = _spec()
    assert spec["permissions"]["contents"] == "write"


def test_the_version_is_ahead_of_every_tag_that_exists():
    """A merge of this repository must always be releasable.

    If pyproject names a version already tagged, the next merge fails at the
    workflow -- correct behaviour, and a state main should never be left in.
    Checked against the tags that exist rather than a version written here,
    which goes stale the moment one is cut.
    """
    version = ""
    for line in (ROOT / "pyproject.toml").read_text().splitlines():
        if line.startswith("version = "):
            version = line.split('"')[1]
            break
    assert version, "pyproject.toml has no version"

    try:
        tags = _tags()
    except (OSError, subprocess.SubprocessError):
        return  # no git, or a checkout without tags; the workflow still checks

    # A check that returns early when its input is missing is not a
    # check. This returned here for the whole life of the repository:
    # CI checked out shallow, `git tag -l` found nothing, and the
    # assertion below never ran -- so main sat at 0.4.0 with v0.4.0
    # tagged, green, and only a local run ever said otherwise.
    #
    # In CI the tags are guaranteed (python-checks.yml is called with
    # fetch-tags: true), so finding none is a broken setup and is
    # reported as one. Off CI it stays a skip: a fresh clone without
    # tags is a normal thing to have.
    if not tags:
        assert not os.environ.get("CI"), (
            "no tags in CI, so the release check could not run. The CI "
            "workflow must call python-checks.yml with fetch-tags: true."
        )
        pytest.skip("no tags in this checkout")
    if f"v{version}" not in tags:
        return
    # On main the version IS tagged, at this very commit: the merge that
    # made HEAD released it, and CI on that push runs beside the tagging.
    # The first run with real tags failed here, on main, one minute after
    # v0.5.0 was cut from the commit it was checking. A tag that points
    # elsewhere is an unbumped version; a tag that points here is a
    # release, which is the state main is meant to be in.
    assert _tag_is_this_commit(f"v{version}"), (
        f"v{version} is already tagged, so the next merge cannot release. "
        "Bump the version in pyproject.toml."
    )


def _tags():
    return subprocess.run(
        ["git", "tag", "-l", "v*"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.split()


def _tag_is_this_commit(tag):
    def rev(name):
        return subprocess.run(
            ["git", "rev-parse", "--verify", f"{name}^{{commit}}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()

    head = rev("HEAD")
    return bool(head) and rev(tag) == head


# --- the release check's own failure paths ----------------------------------
#
# Written with the fix. The check passed for the life of the repository by
# finding no tags and returning, so the one path that ever ran in CI was
# the one that could not fail. Each state is asserted here rather than
# assumed.


def _run_release_check(tags, ci, tagged_here=False):
    """Call the check with a chosen tag list, CI state, and whether the
    version's tag points at the commit under test."""
    import sys
    from unittest import mock

    env = {k: v for k, v in os.environ.items() if k != "CI"}
    if ci:
        env["CI"] = "true"

    me = sys.modules[__name__]
    with (
        mock.patch.object(me, "_tags", return_value=tags.split()),
        mock.patch.object(me, "_tag_is_this_commit", return_value=tagged_here),
        mock.patch.dict(os.environ, env, clear=True),
    ):
        test_the_version_is_ahead_of_every_tag_that_exists()


def test_no_tags_in_ci_is_a_broken_setup_not_a_pass():
    """The bug itself. CI checked out shallow, the check found nothing and
    returned, and main sat at 0.4.0 with v0.4.0 tagged -- green."""
    with pytest.raises(AssertionError, match="no tags in CI"):
        _run_release_check("", ci=True)


def test_no_tags_outside_ci_is_a_skip():
    """A fresh clone without tags is a normal thing to have."""
    with pytest.raises(pytest.skip.Exception):
        _run_release_check("", ci=False)


def test_a_version_that_is_already_tagged_fails():
    version = ""
    for line in (ROOT / "pyproject.toml").read_text().splitlines():
        if line.startswith("version = "):
            version = line.split('"')[1]
            break
    with pytest.raises(AssertionError, match="already tagged"):
        _run_release_check(f"v0.1.0 v{version}", ci=True)


def test_a_version_ahead_of_every_tag_passes():
    _run_release_check("v0.1.0 v0.2.0", ci=True)


def test_a_version_tagged_at_this_commit_is_a_release_not_a_miss():
    """main, one push after a merge: the tag exists because this commit
    is what it points at."""
    version = ""
    for line in (ROOT / "pyproject.toml").read_text().splitlines():
        if line.startswith("version = "):
            version = line.split('"')[1]
            break
    _run_release_check(f"v0.1.0 v{version}", ci=True, tagged_here=True)
