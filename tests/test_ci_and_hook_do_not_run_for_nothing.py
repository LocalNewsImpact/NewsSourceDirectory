"""Two ways this repository ran its whole suite for no reason.

CI: `on: push:` with no branch list runs the workflow on every branch,
and a pull request already runs it on the merge ref -- so each push to a
pull request branch ran lint, the tests, the integration stage, the data
quality rules, the feed and the Pages payload twice. `concurrency` does
not collapse the pair: its group is the ref, and the two runs have
different refs (refs/heads/... against refs/pull/N/merge).

The hook: pre-push receives one line per ref on stdin and a deletion's
local sha is forty zeros. It never read them, so deleting a remote
branch -- which pushes no commits at all -- ran `make check` first.

The crawler and datadesk have both; this brings the pattern here.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github/workflows"
INSTALLER = ROOT / "scripts/setup-hooks.sh"

ZERO = "0" * 40
A_COMMIT = "1" * 40
# What git writes on the hook's stdin: one line per ref being pushed,
# "<local_ref> <local_sha> <remote_ref> <remote_sha>".
PUSHING = f"refs/heads/topic {A_COMMIT} refs/heads/topic {ZERO}\n"
DELETING = f"(delete) {ZERO} refs/heads/topic {A_COMMIT}\n"


def _triggers(name):
    # `on` is YAML 1.1's boolean true, which is why this reads that key.
    return yaml.safe_load((WORKFLOWS / name).read_text())[True]


def test_ci_runs_on_pushes_to_main_only():
    push = _triggers("ci.yml")["push"]
    assert push is not None, "a bare push: runs on every branch"
    assert push["branches"] == ["main"]


def test_ci_still_runs_on_pull_requests():
    """The trigger is narrowed, not the coverage."""
    assert "pull_request" in _triggers("ci.yml")


def _run(command, cwd, env=None, stdin=None):
    # Git exports GIT_DIR to a hook run from a linked worktree. These
    # tests can run inside such a hook, and the scratch `git init` below
    # would then re-initialise the pushing repository.
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        capture_output=True,
        text=True,
        input=stdin,
        env={**clean, **(env or {})},
    )


def _install_into(tmp_path):
    """A scratch git repository with the hook installed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run("git init -q && git config user.email t@e && git config user.name t", repo)
    (repo / "scripts").mkdir()
    shutil.copy(INSTALLER, repo / "scripts" / "setup-hooks.sh")
    os.chmod(repo / "scripts" / "setup-hooks.sh", 0o755)
    result = _run("./scripts/setup-hooks.sh", repo)
    assert result.returncode == 0, result.stderr
    return repo / ".git" / "hooks" / "pre-push"


def _fake_make(repo, exit_code):
    """A `make` on PATH that records its arguments and exits as told."""
    binn = repo / "fakebin"
    binn.mkdir(exist_ok=True)
    make = binn / "make"
    make.write_text(
        f'#!/usr/bin/env bash\necho "make called with: $*" >> "{repo}/make.log"\nexit {exit_code}\n'
    )
    os.chmod(make, 0o755)
    return {"PATH": f"{binn}:{os.environ['PATH']}"}


def test_the_installer_is_valid_shell():
    assert _run(f"bash -n {INSTALLER}", ROOT).returncode == 0


def test_a_branch_deletion_runs_nothing(tmp_path):
    hook = _install_into(tmp_path)
    repo = hook.parent.parent.parent
    env = _fake_make(repo, 1)  # would refuse the push, if it ran at all
    result = _run(str(hook), repo, env, stdin=DELETING)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (repo / "make.log").exists(), "make ran for a deletion"


def test_a_push_that_also_deletes_still_runs_the_checks(tmp_path):
    hook = _install_into(tmp_path)
    repo = hook.parent.parent.parent
    env = _fake_make(repo, 1)
    result = _run(str(hook), repo, env, stdin=DELETING + PUSHING)
    assert result.returncode == 1
    assert "make called with: check" in (repo / "make.log").read_text()


def test_an_empty_stdin_is_not_a_way_past_the_checks(tmp_path):
    """Run by hand there are no refspecs. An empty read has to mean
    "check": the skip is for what git tells us, not for silence."""
    hook = _install_into(tmp_path)
    repo = hook.parent.parent.parent
    env = _fake_make(repo, 1)
    result = _run(str(hook), repo, env, stdin="")
    assert result.returncode == 1
    assert "make called with: check" in (repo / "make.log").read_text()


@pytest.mark.parametrize("workflow", sorted(p.name for p in WORKFLOWS.glob("*.yml")))
def test_no_workflow_pushes_from_every_branch(workflow):
    triggers = _triggers(workflow)
    if not isinstance(triggers, dict) or "push" not in triggers:
        return
    push = triggers["push"]
    # `push:` with nothing under it parses as None, which is the defect
    # itself -- not "no push trigger".
    assert push is not None, f"{workflow} has a bare push:, so every branch runs it"
    assert "branches" in push or "tags" in push, f"{workflow} triggers on every branch"
