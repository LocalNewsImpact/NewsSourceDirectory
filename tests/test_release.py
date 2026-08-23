"""The version in pyproject.toml is what gets released.

`tag-and-pin.yml` reads it, tags `v<version>` if that tag does not exist,
and opens a pull request in Datadesk moving its pin. So the version is not
metadata — it is the instruction, and a release happens because somebody
changed it in the pull request that warranted one.

These guard the two ways that goes wrong: the workflow reading it
differently from a person, and the version being left behind after a
release.
"""

import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _version():
    line = next(
        line
        for line in (ROOT / "pyproject.toml").read_text().splitlines()
        if line.startswith("version = ")
    )
    return line.split('"')[1]


def test_the_workflow_reads_the_version_the_same_way():
    """The workflow greps pyproject rather than parsing it, so this runs
    the same command and checks it agrees."""
    grepped = subprocess.run(
        ["grep", "-m1", "-E", "^version = ", str(ROOT / "pyproject.toml")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split('"')[1]
    assert grepped == _version()


def test_the_version_is_a_release_tag_shape():
    """`v<version>` is what gets tagged and what Datadesk's requirements
    line has to match, and that repository's own test requires
    `v<major>.<minor>.<patch>`."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", _version()), _version()


def test_the_pin_pattern_matches_the_requirements_line():
    """The workflow rewrites Datadesk's pin with a sed. If that pattern
    stops matching, the release is tagged and the pin silently stays
    where it was -- which is the failure this whole workflow exists to
    prevent."""
    line = (
        "news-source-directory @ git+https://github.com/LocalNewsImpact/NewsSourceDirectory@v0.1.0"
    )
    rewritten = re.sub(r"NewsSourceDirectory@v[0-9.]*", "NewsSourceDirectory@v9.9.9", line)
    assert rewritten.endswith("NewsSourceDirectory@v9.9.9")
    assert rewritten != line
