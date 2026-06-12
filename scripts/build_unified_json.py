#!/usr/bin/env python3
"""Collect all registry YAML files and output a unified ai-skills.json."""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Run via `uv run python scripts/build_unified_json.py`.", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = REPO_ROOT / "registry"
OUTPUT_DIR = REPO_ROOT / "dist"
OUTPUT_FILE = OUTPUT_DIR / "ai-skills.json"


def collect_skills() -> list[dict]:
    skills = []
    pattern = str(REGISTRY_DIR / "**" / "*.yaml")
    for filepath in sorted(glob.glob(pattern, recursive=True)):
        with open(filepath, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            skills.append(data)
    return skills


def _stars(skill: dict) -> int:
    metadata = skill.get("metadata") or {}
    if isinstance(metadata, dict):
        try:
            return int(metadata.get("stars", 0) or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def main() -> None:
    skills = collect_skills()
    # Most popular source first (by GitHub stars), then stable by id so a
    # source's skills stay grouped together.
    skills.sort(key=lambda s: (-_stars(s), s.get("id", "")))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(skills, indent=2, ensure_ascii=False)
    OUTPUT_FILE.write_text(json_text + "\n", encoding="utf-8")

    print(f"Wrote {len(skills)} skills to {OUTPUT_FILE.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
