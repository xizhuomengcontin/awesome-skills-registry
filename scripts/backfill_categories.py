#!/usr/bin/env python3
"""Backfill `category` + `tags` (+ refined `display_name`) for registry entries.

Idempotent: only touches entries still at `category: none`, so re-running resumes
where a previous run left off. Classifies in chunks and writes each chunk back
immediately, so partial progress survives an interrupted run.

Usage:
    uv run python scripts/backfill_categories.py                 # all unclassified entries
    uv run python scripts/backfill_categories.py registry/xlsx   # a subset (dir or files)
    uv run python scripts/backfill_categories.py --dry-run ...    # classify + print, don't write
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify import classify  # noqa: E402
from lint_registry import _write_fixed, collect_files  # noqa: E402

_CHUNK = 20


def _targets(paths: list[str] | None) -> list[tuple[Path, dict]]:
    out: list[tuple[Path, dict]] = []
    for fp in collect_files(paths):
        data = yaml.safe_load(fp.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("category", "none") == "none":
            out.append((fp, data))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="dirs/files to limit to (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="classify and print, don't write")
    args = ap.parse_args()

    # collect_files only resolves *.yaml files; expand dir args to their yaml files.
    expanded: list[str] = []
    for p in args.paths:
        path = Path(p)
        if path.is_dir():
            expanded.extend(str(f) for f in path.rglob("*.yaml"))
        else:
            expanded.append(p)

    targets = _targets(expanded or None)
    print(f"{len(targets)} entries to classify (category == none)")
    if not targets:
        return

    counts: Counter[str] = Counter()
    for start in range(0, len(targets), _CHUNK):
        chunk = targets[start : start + _CHUNK]
        items = [
            {"id": d["id"], "display_name": d.get("display_name", ""), "description": d.get("description", "")}
            for _, d in chunk
        ]
        results = classify(items)
        for fp, data in chunk:
            res = results.get(data["id"])
            if not res:
                continue
            data["category"] = res["category"]
            data["tags"] = res["tags"]
            data["display_name"] = res["display_name"]
            counts[res["category"]] += 1
            if args.dry_run:
                print(f"  [dry] {data['id']}: {res['category']} {res['tags']}")
            else:
                _write_fixed(fp, data)

    print("\nCategory distribution:")
    for cat, n in counts.most_common():
        print(f"  {cat:14} {n}")


if __name__ == "__main__":
    main()
