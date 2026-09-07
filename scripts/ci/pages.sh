#!/usr/bin/env bash
# The mockup stays servable and the docs' internal links resolve.
#
# Lifted verbatim from .github/workflows/ci.yml, where it could only ever
# run on a runner. CI now calls `make pages`, so this is the same
# check in both places -- which is the whole point of the suite's shared
# pattern (lnic-contracts docs/shared-ci.md).
#
# The ::error:: lines are GitHub annotations. They are harmless echoes
# locally and worth keeping so a failure points at the same place.
set -euo pipefail

# The caller chooses the interpreter: `make` passes the venv's, so a
# local run uses the same dependencies CI installed.
PYTHON="${PYTHON:-python}"

# --- Mockup stays servable ---------------------------------------
test -f mockup/index.html
test -f .nojekyll
size=$(wc -c < mockup/index.html)
echo "mockup/index.html: $size bytes"
# GitHub Pages serves up to 100MB per file; stay well inside it.
if [ "$size" -gt 20000000 ]; then
  echo "::error::mockup exceeds 20MB"; exit 1
fi

# --- Internal doc links resolve -----------------------------------
#
# Rewritten, not lifted. The original ran the links through a pipeline
# into `while read`, which is a subshell: `fail=1` set inside it was
# discarded, and the check only failed at all through the exit status of
# the pipeline. It also could not distinguish "a link is broken" from
# "this file has no internal links" -- MIGRATION.md carries one external
# link and no internal ones, so under `pipefail` the empty `grep` exits 1
# and the check fails with nothing wrong.
#
# Same rule, stated so it can only fail for the real reason.
broken=0
for f in README.md MIGRATION.md; do
  # `|| true`: no internal links is not a failure.
  links="$(grep -oE '\]\([^)#][^)]*\)' "$f" | sed 's/^](//;s/)$//' | grep -vE '^https?://' || true)"
  [ -z "$links" ] && { echo "$f: no internal links"; continue; }
  n=0
  while IFS= read -r link; do
    target="${link%%#*}"
    [ -z "$target" ] && continue
    n=$((n + 1))
    if [ ! -e "$target" ]; then
      echo "::error file=$f::broken link: $target"
      broken=$((broken + 1))
    fi
  done <<< "$links"
  echo "$f: $n internal link(s) checked"
done

if [ "$broken" -ne 0 ]; then
  echo "::error::$broken broken internal link(s)"
  exit 1
fi
echo "every internal link resolves."
