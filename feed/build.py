"""Build the public static feed.

Emits content-addressed data files plus a small manifest that names them:

    feed/manifest.json               short cache TTL, always revalidated
    feed/sites.<sha8>.json           immutable — loaded eagerly, first paint
    feed/coverage.<sha8>.json        immutable — loaded lazily, on drill-down

Content hashing is what makes this work on a bare GCS bucket with no CDN: the
manifest is the only file that ever needs revalidating, and everything it points
at can be cached for a year. A publish writes new hashed files and swaps the
manifest, so a reader never sees a half-updated feed.

Each file carries a `load` hint. `sites` is eager — it is what the directory
renders. `coverage` is lazy: roughly twice the size and needed only when someone
opens the coverage view or drills into one outlet, so most visitors never fetch
it. The client is told this rather than guessing.

Output is deterministic — sorted keys, sorted rows, hash independent of build
time — so an unchanged dataset produces an unchanged hash and no redeploy.
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

from checks.rules import COVERAGE_PUBLIC_FIELDS, PUBLIC_FIELDS, Severity, run_all

SCHEMA_VERSION = 2
Row = dict[str, str]


def load_csv(path: Path) -> list[Row]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _project(rows: Iterable[Row], allowed: frozenset[str], sort_key) -> list[Row]:
    out = [{k: (r.get(k) or "").strip() for k in sorted(set(r) & allowed)} for r in rows]
    out.sort(key=sort_key)
    return out


def public_view(outlets: Iterable[Row]) -> list[Row]:
    """Project outlets onto the public allowlist.

    Projection happens here and nowhere else. A column added upstream is absent
    from the feed until it is added to PUBLIC_FIELDS deliberately.
    """
    return _project(
        outlets,
        PUBLIC_FIELDS,
        lambda r: (r.get("outlet_name", ""), r.get("outlet_id", "")),
    )


def coverage_view(coverage: Iterable[Row]) -> list[Row]:
    """Project coverage records onto their own allowlist."""
    return _project(
        coverage,
        COVERAGE_PUBLIC_FIELDS,
        lambda r: (r.get("outlet_id", ""), r.get("source_file", ""), r.get("outlet_name_raw", "")),
    )


def _canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _write(out_dir: Path, stem: str, rows: list[Row], load: str, **extra) -> dict:
    blob = _canonical(rows)
    sha = hashlib.sha256(blob).hexdigest()
    name = f"{stem}.{sha[:8]}.json"
    (out_dir / name).write_bytes(blob)
    return {
        "path": name,
        "sha256": sha,
        "bytes": len(blob),
        "rows": len(rows),
        "load": load,
        "fields": sorted(rows[0]) if rows else [],
        **extra,
    }


def build_feed(
    outlets: Sequence[Row],
    coverage: Sequence[Row] = (),
    out_dir: Path = Path("dist/feed"),
    generated_at: str | None = None,
    allow_errors: bool = False,
    include_coverage: bool = True,
) -> dict:
    """Validate, project, and write the feed. Returns the manifest."""
    sites = public_view(outlets)
    cover = coverage_view(coverage) if (include_coverage and coverage) else []

    violations = run_all(outlets, coverage, export=sites, coverage_export=cover or None)
    errors = [v for v in violations if v.severity is Severity.ERROR]
    if errors and not allow_errors:
        raise ValueError(f"refusing to publish: {len(errors)} error(s), first: {errors[0]}")

    out_dir.mkdir(parents=True, exist_ok=True)
    files = {"sites": _write(out_dir, "sites", sites, "eager")}
    if cover:
        files["coverage"] = _write(
            out_dir, "coverage", cover, "lazy", join_key="outlet_id", joins_to="sites"
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {"outlets": len(sites), "coverage_records": len(cover)},
        "errors_present": len(errors),
        "warnings": sum(1 for v in violations if v.severity is Severity.WARN),
        "files": files,
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
        "--no-coverage-feed",
        action="store_true",
        help="validate against coverage but do not publish it",
    )
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
            include_coverage=not args.no_coverage_feed,
        )
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    for meta in manifest["files"].values():
        print(
            f"  {meta['load']:6s} {args.out}/{meta['path']}"
            f"  {meta['rows']} rows, {meta['bytes'] / 1024:.1f}KB"
        )
    print(f"  manifest {args.out}/manifest.json")
    if manifest["errors_present"]:
        print(f"  published with {manifest['errors_present']} rule error(s) — --allow-errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
