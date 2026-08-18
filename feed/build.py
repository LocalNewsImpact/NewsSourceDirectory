"""Build the public static feed.

Emits content-addressed data files plus a small manifest that names them:

    feed/manifest.json                  short cache TTL, always refetched
    feed/sites.<sha8>.json              immutable, cache forever
    feed/search-index.<sha8>.json       immutable, cache forever  (built by Node)

The content hash is what makes this work on a bare GCS bucket with no CDN: the
manifest is the only file that ever needs revalidating, and the payload it points
at can be cached for a year. A new publish writes new hashed files and swaps the
manifest, so a reader never sees a half-updated feed.

Output is deterministic — sorted keys, sorted rows — so an unchanged dataset
produces an unchanged hash and no pointless redeploy.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from checks.rules import PUBLIC_FIELDS, Severity, run_all

SCHEMA_VERSION = 1
Row = dict[str, str]


def load_csv(path: Path) -> list[Row]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def public_view(outlets: Iterable[Row], fields: Sequence[str] | None = None) -> list[Row]:
    """Project outlets onto the public allowlist.

    Projection happens here and nowhere else. A column added upstream is absent
    from the feed until it is added to PUBLIC_FIELDS deliberately.
    """
    rows = []
    for o in outlets:
        keep = fields if fields is not None else sorted(set(o) & PUBLIC_FIELDS)
        rows.append({k: (o.get(k) or "").strip() for k in keep})
    rows.sort(key=lambda r: (r.get("outlet_name", ""), r.get("outlet_id", "")))
    return rows


def _canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def build_feed(
    outlets: Sequence[Row],
    coverage: Sequence[Row] = (),
    out_dir: Path = Path("dist/feed"),
    generated_at: str | None = None,
    allow_errors: bool = False,
) -> dict:
    """Validate, project, and write the feed. Returns the manifest."""
    rows = public_view(outlets)

    violations = run_all(outlets, coverage, export=rows)
    errors = [v for v in violations if v.severity is Severity.ERROR]
    if errors and not allow_errors:
        raise ValueError(f"refusing to publish: {len(errors)} error(s), first: {errors[0]}")

    blob = _canonical(rows)
    sha = _digest(blob)
    name = f"sites.{sha[:8]}.json"

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_bytes(blob)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {"outlets": len(rows), "coverage_records": len(coverage)},
        "fields": sorted(rows[0]) if rows else [],
        "errors_present": len(errors),
        "warnings": sum(1 for v in violations if v.severity is Severity.WARN),
        "files": {
            "sites": {"path": name, "sha256": sha, "bytes": len(blob)},
        },
    }
    (out_dir / "manifest.json").write_bytes(_canonical(manifest))
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="feed", description=__doc__)
    ap.add_argument("outlets", type=Path)
    ap.add_argument("--coverage", type=Path)
    ap.add_argument("--out", type=Path, default=Path("dist/feed"))
    ap.add_argument("--generated-at", help="fixed timestamp, for reproducible builds")
    ap.add_argument(
        "--allow-errors",
        action="store_true",
        help="publish despite rule errors (the prototype data still has 302)",
    )
    args = ap.parse_args(argv)

    outlets = load_csv(args.outlets)
    coverage = load_csv(args.coverage) if args.coverage else []

    try:
        manifest = build_feed(
            outlets,
            coverage,
            out_dir=args.out,
            generated_at=args.generated_at,
            allow_errors=args.allow_errors,
        )
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    sites = manifest["files"]["sites"]
    print(f"wrote {args.out}/{sites['path']}  ({sites['bytes'] / 1024:.1f}KB)")
    print(f"      {args.out}/manifest.json")
    print(f"      {manifest['counts']['outlets']} outlets, fields: {', '.join(manifest['fields'])}")
    if manifest["errors_present"]:
        print(f"      published with {manifest['errors_present']} rule error(s) — --allow-errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
