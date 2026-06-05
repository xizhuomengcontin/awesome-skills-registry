#!/usr/bin/env python3
"""Lint and auto-fix registry YAML files.

Checks every *.yaml file under registry/ for common quality issues
and optionally fixes them in-place.

Usage:
    uv run python scripts/lint_registry.py              # check only (exit 1 if issues found)
    uv run python scripts/lint_registry.py --fix        # auto-fix all fixable issues
    uv run python scripts/lint_registry.py path/to.yaml # check a specific file
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Run via `uv run python scripts/lint_registry.py`.", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = REPO_ROOT / "registry"

REQUIRED_FIELDS = ("id", "display_name", "description", "authors", "is_official", "tags", "category", "source", "metadata", "added_at")

VALID_CATEGORIES = frozenset({
    "none", "coding", "design", "productivity", "marketing", "business",
    "data-ai", "science", "creative", "health", "legal", "miscellaneous",
})


@dataclass
class LintIssue:
    file: str
    rule: str
    message: str
    fixable: bool = False


@dataclass
class LintResult:
    issues: list[LintIssue] = field(default_factory=list)
    files_checked: int = 0
    files_fixed: int = 0


def _normalize_description(desc: str) -> str:
    """Collapse whitespace artifacts from YAML block-scalar folding."""
    text = desc.strip()
    text = re.sub(r"\n{2,}", " ", text)
    text = re.sub(r"\n", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def lint_file(filepath: Path, fix: bool = False) -> list[LintIssue]:
    """Lint a single registry YAML file. Returns list of issues found."""
    try:
        rel = filepath.relative_to(REPO_ROOT)
    except ValueError:
        rel = filepath
    issues: list[LintIssue] = []

    raw_text = filepath.read_text(encoding="utf-8")

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        issues.append(LintIssue(str(rel), "yaml-parse-error", f"Invalid YAML: {exc}"))
        return issues

    if not isinstance(data, dict):
        issues.append(LintIssue(str(rel), "yaml-not-mapping", "File does not contain a YAML mapping"))
        return issues

    for field_name in REQUIRED_FIELDS:
        if field_name not in data or data[field_name] is None:
            issues.append(LintIssue(str(rel), "missing-field", f"Missing required field: {field_name}"))

    source = data.get("source")
    if source is not None:
        if not isinstance(source, dict):
            issues.append(LintIssue(str(rel), "source-not-mapping", "Field 'source' must be a mapping"))
        else:
            if "repo" not in source:
                issues.append(LintIssue(str(rel), "missing-field", "Missing required field: source.repo"))
            if "path" not in source:
                issues.append(LintIssue(str(rel), "missing-field", "Missing required field: source.path"))

    display_name = data.get("display_name")
    if display_name is not None and (not isinstance(display_name, str) or not display_name.strip()):
        issues.append(LintIssue(str(rel), "display-name-empty", "Field 'display_name' must be a non-empty string"))

    authors = data.get("authors")
    if authors is not None:
        if not isinstance(authors, list):
            issues.append(LintIssue(str(rel), "authors-not-list", "Field 'authors' must be a list"))
        elif not authors:
            issues.append(LintIssue(str(rel), "authors-empty", "Field 'authors' is an empty list"))

    is_official = data.get("is_official")
    if is_official is not None and not isinstance(is_official, bool):
        issues.append(LintIssue(str(rel), "is-official-not-bool", "Field 'is_official' must be a boolean"))

    tags = data.get("tags")
    if tags is not None and not isinstance(tags, list):
        issues.append(LintIssue(str(rel), "tags-not-list", "Field 'tags' must be a list"))

    category = data.get("category")
    if category is not None and category not in VALID_CATEGORIES:
        issues.append(LintIssue(
            str(rel), "category-invalid",
            f"Invalid category '{category}'; must be one of: {', '.join(sorted(VALID_CATEGORIES))}",
        ))

    desc = data.get("description")
    if desc is not None:
        desc = str(desc)
        needs_fix = False

        if not desc.strip():
            issues.append(LintIssue(str(rel), "description-empty", "Description is empty"))

        if "\n\n" in desc:
            issues.append(LintIssue(
                str(rel), "description-blank-lines",
                "Description contains blank lines (likely YAML folding artifact)",
                fixable=True,
            ))
            needs_fix = True

        if desc != desc.strip():
            issues.append(LintIssue(
                str(rel), "description-surrounding-whitespace",
                "Description has leading or trailing whitespace/newlines",
                fixable=True,
            ))
            needs_fix = True

        if re.search(r" {2,}", desc):
            issues.append(LintIssue(
                str(rel), "description-multiple-spaces",
                "Description contains consecutive spaces",
                fixable=True,
            ))
            needs_fix = True

        if "\n" in desc.strip() and "\n\n" not in desc:
            issues.append(LintIssue(
                str(rel), "description-internal-newlines",
                "Description contains single newlines (may be unintended line breaks)",
                fixable=True,
            ))
            needs_fix = True

        if fix and needs_fix:
            data["description"] = _normalize_description(desc)

    if not raw_text.endswith("\n"):
        issues.append(LintIssue(str(rel), "no-final-newline", "File does not end with a newline", fixable=True))

    if raw_text.endswith("\n\n"):
        issues.append(LintIssue(str(rel), "trailing-blank-lines", "File has trailing blank lines", fixable=True))

    if fix and any(i.fixable for i in issues):
        _write_fixed(filepath, data)

    return issues


def _write_fixed(filepath: Path, data: dict) -> None:
    """Re-serialize and write the fixed YAML, preserving field order."""
    field_order = ["id", "display_name", "description", "authors", "is_official", "tags", "category", "source", "metadata", "added_at"]
    ordered: dict = {}
    for key in field_order:
        if key in data:
            ordered[key] = data[key]
    for key in data:
        if key not in ordered:
            ordered[key] = data[key]

    output = yaml.dump(ordered, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120)
    filepath.write_text(output, encoding="utf-8")


def collect_files(paths: list[str] | None = None) -> list[Path]:
    """Resolve target files — explicit paths or all registry YAMLs."""
    if paths:
        return [Path(p).resolve() for p in paths if p.endswith(".yaml")]

    pattern = str(REGISTRY_DIR / "**" / "*.yaml")
    return sorted(Path(p) for p in glob.glob(pattern, recursive=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Lint registry YAML files")
    parser.add_argument("files", nargs="*", help="Specific files to lint (default: all registry/*.yaml)")
    parser.add_argument("--fix", action="store_true", help="Auto-fix fixable issues in-place")
    args = parser.parse_args()

    targets = collect_files(args.files or None)
    result = LintResult(files_checked=len(targets))

    for filepath in targets:
        file_issues = lint_file(filepath, fix=args.fix)
        if file_issues:
            result.issues.extend(file_issues)
            if args.fix and any(i.fixable for i in file_issues):
                result.files_fixed += 1

    if args.fix and result.files_fixed:
        print(f"Fixed {result.files_fixed} file(s)")

    if result.issues:
        fixable = [i for i in result.issues if i.fixable]
        unfixable = [i for i in result.issues if not i.fixable]

        for issue in result.issues:
            marker = " [fixable]" if issue.fixable else ""
            status = " [fixed]" if (args.fix and issue.fixable) else ""
            print(f"{issue.file}: {issue.rule}: {issue.message}{marker}{status}")

        print()
        print(f"Checked {result.files_checked} files")
        print(f"Found {len(result.issues)} issue(s): {len(fixable)} fixable, {len(unfixable)} unfixable")

        if not args.fix and fixable:
            print("\nRun with --fix to auto-fix fixable issues.")

        if not args.fix:
            sys.exit(1)
    else:
        print(f"Checked {result.files_checked} files — no issues found.")


if __name__ == "__main__":
    main()
