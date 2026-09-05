#!/usr/bin/env bash
# The public feed carries no admin columns, joins cleanly, and builds reproducibly.
#
# Lifted verbatim from .github/workflows/ci.yml, where it could only ever
# run on a runner. CI now calls `make feed-check`, so this is the same
# check in both places -- which is the whole point of the suite's shared
# pattern (lnic-contracts docs/shared-ci.md).
#
# The ::error:: lines are GitHub annotations. They are harmless echoes
# locally and worth keeping so a failure points at the same place.
set -euo pipefail

# The caller chooses the interpreter: `make` passes the venv's, so a
# local run uses the same dependencies CI installed.
PYTHON="${PYTHON:-python}"

# --- Build the feed from the fixture -----------------------------
"$PYTHON" -m feed tests/fixtures/outlets_sample.csv \
  --coverage tests/fixtures/coverage_sample.csv \
  --out dist/feed --generated-at 2026-01-01T00:00:00Z --allow-errors
cat dist/feed/manifest.json

# --- Feed carries no admin columns -------------------------------
"$PYTHON" - <<'PY'
import json, pathlib, sys
sys.path.insert(0, ".")
from checks.rules import PUBLIC_FIELDS
from checks.rules import COVERAGE_PUBLIC_FIELDS
base = pathlib.Path("dist/feed")
m = json.loads((base / "manifest.json").read_text())

rows = json.loads((base / m["files"]["sites"]["path"]).read_text())
extra = sorted({k for r in rows for k in r} - PUBLIC_FIELDS)
if extra:
    print(f"::error::sites feed carries non-public columns: {extra}")
    raise SystemExit(1)
print(f"sites: {len(rows)} rows, fields all allowlisted")

cov_meta = m["files"].get("coverage")
if not cov_meta:
    print("::error::coverage feed was not published")
    raise SystemExit(1)
cov = json.loads((base / cov_meta["path"]).read_text())
extra = sorted({k for r in cov for k in r} - COVERAGE_PUBLIC_FIELDS)
if extra:
    print(f"::error::coverage feed carries non-public columns: {extra}")
    raise SystemExit(1)
print(f"coverage: {len(cov)} rows, fields all allowlisted")

if m["files"]["sites"]["load"] != "eager" or cov_meta["load"] != "lazy":
    print("::error::load hints wrong; sites must be eager and coverage lazy")
    raise SystemExit(1)

known = {r["outlet_id"] for r in rows}
orphans = {r["outlet_id"] for r in cov} - known
if orphans:
    print(f"::error::coverage rows with no published outlet: {sorted(orphans)[:5]}")
    raise SystemExit(1)
print("coverage joins cleanly to sites on outlet_id")
PY

# --- Search index builds against the same feed -------------------
node tools/build-search-index.mjs dist/feed

# --- Feed build is reproducible ----------------------------------
cp dist/feed/manifest.json /tmp/first.json
rm -rf dist
"$PYTHON" -m feed tests/fixtures/outlets_sample.csv \
  --coverage tests/fixtures/coverage_sample.csv \
  --out dist/feed --generated-at 2026-01-01T00:00:00Z --allow-errors
"$PYTHON" - <<'PY'
import json, pathlib
a = json.loads(pathlib.Path("/tmp/first.json").read_text())
b = json.loads(pathlib.Path("dist/feed/manifest.json").read_text())
if a["files"]["sites"]["sha256"] != b["files"]["sites"]["sha256"]:
    print("::error::feed build is not reproducible")
    raise SystemExit(1)
print("reproducible:", b["files"]["sites"]["sha256"][:12])
PY
