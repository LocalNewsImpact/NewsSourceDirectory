#!/usr/bin/env bash
# The rules still detect the defects the fixture carries.
#
# Lifted verbatim from .github/workflows/ci.yml, where it could only ever
# run on a runner. CI now calls `make data-quality`, so this is the same
# check in both places -- which is the whole point of the suite's shared
# pattern (lnic-contracts docs/shared-ci.md).
#
# The ::error:: lines are GitHub annotations. They are harmless echoes
# locally and worth keeping so a failure points at the same place.
set -euo pipefail

# The caller chooses the interpreter: `make` passes the venv's, so a
# local run uses the same dependencies CI installed.
PYTHON="${PYTHON:-python}"

# --- Rules detect the known defects ------------------------------
set +e
"$PYTHON" -m checks tests/fixtures/outlets_sample.csv \
  --coverage tests/fixtures/coverage_sample.csv | tee report.txt
status=${PIPESTATUS[0]}
set -e
if [ "$status" -eq 0 ]; then
  echo "::error::Fixture passed all rules — the defect detection has regressed."
  exit 1
fi
for rule in no_placeholder_domain merge_requires_review no_header_artifacts no_url_in_medium; do
  grep -q "$rule" report.txt || { echo "::error::$rule no longer fires"; exit 1; }
done
echo "All expected defects detected."
