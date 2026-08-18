"""Run the data-quality rules over CSV or JSON exports.

    python -m checks outlets.csv --coverage coverage.csv
    python -m checks outlets.csv --coverage coverage.csv --export sites.json

Exits non-zero if any ERROR is found. WARNs are reported and do not fail, so a
curation backlog never blocks a deploy.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from checks.rules import Severity, run_all


def load(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data.get("outlets", [])
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="checks", description=__doc__)
    ap.add_argument("outlets", type=Path)
    ap.add_argument("--coverage", type=Path)
    ap.add_argument("--export", type=Path, help="the file about to be published")
    ap.add_argument("--max-warn", type=int, default=None, help="fail if warnings exceed this")
    args = ap.parse_args(argv)

    outlets = load(args.outlets)
    coverage = load(args.coverage) if args.coverage else []
    export = load(args.export) if args.export else None

    violations = run_all(outlets, coverage, export)
    errors = [v for v in violations if v.severity is Severity.ERROR]
    warns = [v for v in violations if v.severity is Severity.WARN]

    print(f"{len(outlets)} outlets, {len(coverage)} coverage records")

    for label, group in (("ERRORS", errors), ("WARNINGS", warns)):
        if not group:
            continue
        print(f"\n{label} ({len(group)})")
        for rule, n in Counter(v.rule for v in group).most_common():
            print(f"  {n:5d}  {rule}")
        for v in group[:15]:
            print(f"    {v}")
        if len(group) > 15:
            print(f"    ... and {len(group) - 15} more")

    if not violations:
        print("\nAll rules passed.")

    if errors:
        print(f"\nFAIL: {len(errors)} error(s)")
        return 1
    if args.max_warn is not None and len(warns) > args.max_warn:
        print(f"\nFAIL: {len(warns)} warnings exceeds --max-warn {args.max_warn}")
        return 1
    print(f"\nOK ({len(warns)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
