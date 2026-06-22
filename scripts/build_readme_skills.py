#!/usr/bin/env python3
"""Generate the README "Skills" listing, grouped by publisher.

Reads every registry YAML entry, groups skills by their source repo owner
("publisher"), and renders a collapsible list between the
``<!-- skills-list-start -->`` / ``<!-- skills-list-end -->`` markers in
README.md. The most popular publishers (by GitHub stars) are expanded by
default; the rest render as collapsed ``<details>`` blocks.

The section is regenerated in place on every run, so new skills that land in
the registry are picked up automatically without duplicating existing ones.

Usage:
    uv run python scripts/build_readme_skills.py
    uv run python scripts/build_readme_skills.py --open 10
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "Error: PyYAML is required. Run via `uv run python scripts/build_readme_skills.py`.",
        file=sys.stderr,
    )
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = REPO_ROOT / "registry"
README = REPO_ROOT / "README.md"

START_MARKER = "<!-- skills-list-start -->"
END_MARKER = "<!-- skills-list-end -->"

# How many publishers to expand by default; the rest are collapsed.
DEFAULT_OPEN = 8

# Max skills to list per publisher before linking out to "view all".
MAX_ITEMS = 10

# Nicely-cased display names for publishers we know about. Everything else is
# humanized automatically from the owner slug.
PUBLISHER_OVERRIDES = {
    "anthropics": "Official Claude Skills",
    "voltagent": "VoltAgent",
    "composiohq": "Composio",
    "google-gemini": "Google Gemini",
    "googleapis": "Google",
    "coderabbit": "CodeRabbit",
    "coderabbitai": "CodeRabbit",
    "browserbase": "Browserbase",
    "apollographql": "Apollo GraphQL",
    "auth0": "Auth0",
    "openai": "OpenAI",
    "supabase": "Supabase",
    "huggingface": "Hugging Face",
    "datadog": "Datadog",
    "github": "GitHub",
    "gitlab": "GitLab",
    "vercel": "Vercel",
    "stripe": "Stripe",
    "cloudflare": "Cloudflare",
    "mongodb": "MongoDB",
    "postgresml": "PostgresML",
}


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


def _repo(skill: dict) -> str:
    source = skill.get("source") or {}
    return str(source.get("repo") or "").strip()


def _path(skill: dict) -> str:
    source = skill.get("source") or {}
    return str(source.get("path") or "").strip()


def _owner(skill: dict) -> str:
    repo = _repo(skill)
    return repo.split("/")[0] if "/" in repo else repo


def humanize(owner: str) -> str:
    if owner in PUBLISHER_OVERRIDES:
        return PUBLISHER_OVERRIDES[owner]
    words = re.split(r"[-_.\s]+", owner)
    return " ".join(w[:1].upper() + w[1:] for w in words if w) or owner


def skill_label(skill: dict) -> str:
    # Skills are grouped under their publisher, so the owner prefix is
    # redundant — show just the leaf name (e.g. ``ab-testing``).
    path = _path(skill)
    repo = _repo(skill)
    if path and path not in ("/", ""):
        return path.rstrip("/").rsplit("/", 1)[-1]
    if "/" in repo:
        return repo.split("/", 1)[1]
    return repo


def skill_url(skill: dict) -> str:
    repo = _repo(skill)
    path = _path(skill)
    if not repo:
        return ""
    if path and path not in ("/", ""):
        return f"https://github.com/{repo}/tree/HEAD/{path.lstrip('/')}"
    return f"https://github.com/{repo}"


def provider_url(skills: list[dict]) -> str:
    """Best link for browsing all of a publisher's skills.

    If every skill shares one source repo, link to that repo; otherwise fall
    back to the publisher's GitHub profile.
    """
    repos = {_repo(s) for s in skills if _repo(s)}
    if len(repos) == 1:
        return f"https://github.com/{next(iter(repos))}"
    owner = _owner(skills[0]) if skills else ""
    return f"https://github.com/{owner}" if owner else ""


def short_description(text: str, limit: int = 110) -> str:
    text = " ".join((text or "").split())
    if not text:
        return ""
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    if len(first) > limit:
        first = first[: limit - 1].rstrip() + "…"
    return first


def display_name(skill: dict) -> str:
    return str(skill.get("display_name") or skill.get("id") or "").strip()


def render_group(name: str, skills: list[dict], *, is_open: bool, official: bool) -> str:
    stars = max((_stars(s) for s in skills), default=0)
    count = len(skills)
    noun = "skill" if count == 1 else "skills"

    # Stars lead the inline meta, shown right alongside the publisher name.
    meta_bits = []
    if stars:
        meta_bits.append(f"⭐ {stars:,}")
    meta_bits.append(f"{count} {noun}")
    if official:
        meta_bits.append("official")
    meta = " · ".join(meta_bits)

    ordered = sorted(skills, key=lambda x: display_name(x).lower())
    items = []
    for s in ordered[:MAX_ITEMS]:
        label = skill_label(s)
        url = skill_url(s)
        desc = short_description(s.get("description", ""))
        link = f"[`{label}`]({url})" if url else f"`{label}`"
        items.append(f"- {link} — {desc}" if desc else f"- {link}")

    if count > MAX_ITEMS:
        more = provider_url(skills)
        if more:
            items.append(f"- [**View all {count} skills →**]({more})")

    # Tight list (no blank lines) keeps each publisher compact and readable.
    body = "\n".join(items)

    lines = [
        f"<details{' open' if is_open else ''}>",
        f"<summary><h3>{name} &nbsp;<sub>{meta}</sub></h3></summary>",
        "",
        body,
        "",
        "</details>",
    ]
    return "\n".join(lines)


def build_section(skills: list[dict], open_count: int) -> str:
    groups: dict[str, list[dict]] = {}
    for s in skills:
        owner = _owner(s)
        if not owner:
            continue
        groups.setdefault(owner, []).append(s)

    ordered = sorted(
        groups.items(),
        key=lambda kv: (-max((_stars(s) for s in kv[1]), default=0), kv[0].lower()),
    )

    blocks = []
    for idx, (owner, group) in enumerate(ordered):
        name = humanize(owner)
        official = any(bool(s.get("is_official")) for s in group)
        blocks.append(
            render_group(name, group, is_open=idx < open_count, official=official)
        )
    return "\n\n<br/>\n\n".join(blocks)


def write_readme(section: str) -> None:
    text = README.read_text(encoding="utf-8")
    if START_MARKER not in text or END_MARKER not in text:
        print(
            f"Error: markers {START_MARKER} / {END_MARKER} not found in README.md.",
            file=sys.stderr,
        )
        sys.exit(1)
    pattern = re.compile(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL
    )
    replacement = f"{START_MARKER}\n\n{section}\n\n{END_MARKER}"
    README.write_text(pattern.sub(replacement, text), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--open",
        type=int,
        default=DEFAULT_OPEN,
        help=f"number of top publishers to expand by default (default: {DEFAULT_OPEN})",
    )
    args = parser.parse_args()

    skills = collect_skills()
    section = build_section(skills, args.open)
    write_readme(section)

    publishers = len({_owner(s) for s in skills if _owner(s)})
    print(
        f"Updated README skills listing: {len(skills)} skills across {publishers} publishers."
    )


if __name__ == "__main__":
    main()
