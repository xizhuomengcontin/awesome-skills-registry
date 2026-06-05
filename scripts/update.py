#!/usr/bin/env python3
"""Scan configured source repos for SKILL.md files and update the registry."""

from __future__ import annotations

import argparse
import functools
import glob
import logging
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import yaml
from github import Github, GithubException
from rapidfuzz import fuzz

MAX_SCAN_WORKERS = 10
MAX_FETCH_WORKERS = 15

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = REPO_ROOT / "registry"
SOURCES_PATH = REPO_ROOT / "sources.yaml"
SIMILARITY_THRESHOLD = 75


def retry(max_attempts: int = 3, base_delay: float = 1.0):
    """Retry decorator with exponential backoff for transient failures."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except GithubException as exc:
                    last_exc = exc
                    if attempt < max_attempts - 1:
                        delay = base_delay * (2**attempt)
                        logger.warning(
                            "GitHub API error (attempt %d/%d): %s — retrying in %.1fs",
                            attempt + 1,
                            max_attempts,
                            exc,
                            delay,
                        )
                        time.sleep(delay)
            raise last_exc

        return wrapper

    return decorator


@dataclass
class Source:
    url: str
    owner: str
    repo: str
    skills_path: str = "/"
    skills_paths: list[str] = field(default_factory=list)  # canonical list, always populated
    skill_filename: str = "SKILL.md"


@dataclass
class SkillFile:
    owner: str
    repo: str
    skill_dir: str
    path: str
    raw_url: str
    skill_filename: str = "SKILL.md"
    folder_url: str = ""


@dataclass
class RegistryEntry:
    folder: str
    filename: str
    name: str
    description: str
    comparison_text: str


def load_sources(path: Path = SOURCES_PATH) -> list[Source]:
    """Parse sources.yaml and return deduplicated Source objects."""
    with open(path) as f:
        data = yaml.safe_load(f)

    seen: set[tuple[str, str, str]] = set()
    sources: list[Source] = []

    for entry in data.get("sources", []):
        url = entry["url"]
        parsed = urlparse(url)
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 2:
            logger.warning("Skipping invalid source URL: %s", url)
            continue

        owner, repo = parts[0], parts[1]
        skills_path = entry.get("skills_path", "/")
        if skills_path != "/" and not skills_path.endswith("/"):
            skills_path += "/"

        # skills_paths (plural) supports multiple root-level dirs with no common parent
        skills_paths_raw = entry.get("skills_paths", [])
        if skills_paths_raw:
            skills_paths = []
            for p in skills_paths_raw:
                p = str(p)
                if p != "/" and not p.endswith("/"):
                    p += "/"
                skills_paths.append(p)
        else:
            skills_paths = [skills_path]

        skill_filename = entry.get("skill_filename", "SKILL.md")

        key = (owner, repo, str(skills_paths), skill_filename)
        if key in seen:
            continue
        seen.add(key)

        sources.append(Source(
            url=url,
            owner=owner,
            repo=repo,
            skills_path=skills_path,
            skills_paths=skills_paths,
            skill_filename=skill_filename,
        ))

    return sources


def _build_raw_url(owner: str, repo: str, default_branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/{path}"


def _build_folder_url(owner: str, repo: str, default_branch: str, folder_path: str) -> str:
    if not folder_path or folder_path in (".", "/"):
        return f"https://github.com/{owner}/{repo}/tree/{default_branch}"
    return f"https://github.com/{owner}/{repo}/tree/{default_branch}/{folder_path}"


@retry()
def _walk_contents(
    repo,
    dir_path: str,
    owner: str,
    repo_name: str,
    default_branch: str,
    skill_filename: str = "SKILL.md",
) -> list[SkillFile]:
    """Recursively walk a directory and collect SKILL.md files."""
    results: list[SkillFile] = []

    try:
        contents = repo.get_contents(dir_path)
    except GithubException as exc:
        if exc.status == 404:
            return []
        raise

    if not isinstance(contents, list):
        contents = [contents]

    for item in contents:
        if item.type == "dir":
            results.extend(
                _walk_contents(repo, item.path, owner, repo_name, default_branch, skill_filename)
            )
        elif item.name == skill_filename:
            skill_dir = Path(item.path).parent.name
            skill_folder_path = str(Path(item.path).parent)
            if not skill_dir or skill_dir == ".":
                skill_dir = f"skill-{len(results)}"
            results.append(
                SkillFile(
                    owner=owner,
                    repo=repo_name,
                    skill_dir=skill_dir,
                    path=item.path,
                    raw_url=_build_raw_url(owner, repo_name, default_branch, item.path),
                    folder_url=_build_folder_url(owner, repo_name, default_branch, skill_folder_path),
                    skill_filename=skill_filename,
                )
            )

    return results


def find_skill_files(source: Source, github: Github) -> list[SkillFile]:
    """Find all skill files in a source repo based on its skills_paths and skill_filename."""
    repo = github.get_repo(f"{source.owner}/{source.repo}")
    default_branch = repo.default_branch
    results: list[SkillFile] = []

    for path in source.skills_paths:
        if path == "/":
            try:
                content = repo.get_contents(source.skill_filename)
            except GithubException as exc:
                if exc.status == 404:
                    continue
                raise

            if isinstance(content, list):
                content = content[0]

            results.append(
                SkillFile(
                    owner=source.owner,
                    repo=source.repo,
                    skill_dir="root",
                    path=source.skill_filename,
                    raw_url=_build_raw_url(
                        source.owner, source.repo, default_branch, source.skill_filename
                    ),
                    folder_url=_build_folder_url(
                        source.owner, source.repo, default_branch, ""
                    ),
                    skill_filename=source.skill_filename,
                )
            )
        else:
            results.extend(_walk_contents(
                repo, path.rstrip("/"), source.owner, source.repo, default_branch, source.skill_filename
            ))

    return results


def already_registered(owner: str, repo: str, skill_dir: str) -> bool:
    """Check if a skill is already present in the registry."""
    pattern = str(REGISTRY_DIR / "**" / f"{owner}-{repo}-{skill_dir}.yaml")
    return bool(glob.glob(pattern, recursive=True))


def extract_metadata(content: str) -> dict[str, str]:
    """Extract name and description from SKILL.md content."""
    name = ""
    description = ""

    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if frontmatter_match:
        try:
            fm = yaml.safe_load(frontmatter_match.group(1))
            if isinstance(fm, dict):
                name = str(fm.get("name", "") or "")
                description = str(fm.get("description", "") or "")
                if name or description:
                    return {"name": name, "description": description}
        except yaml.YAMLError:
            pass

    name_match = re.search(r"^#\s*Skill:\s*(.+)$", content, re.MULTILINE)
    if name_match:
        name = name_match.group(1).strip()

    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            description = stripped
            break

    return {"name": name, "description": description}


def build_comparison_text(name: str, description: str) -> str:
    return f"{name} {description}".strip()


def build_registry_index() -> list[RegistryEntry]:
    """Build an index of all existing registry entries."""
    entries: list[RegistryEntry] = []

    for filepath in glob.glob(str(REGISTRY_DIR / "**" / "*.yaml"), recursive=True):
        with open(filepath) as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            continue

        name = str(data.get("id", "") or "")
        description = str(data.get("description", "") or "")
        folder = Path(filepath).parent.name
        filename = Path(filepath).name

        entries.append(
            RegistryEntry(
                folder=folder,
                filename=filename,
                name=name,
                description=description,
                comparison_text=build_comparison_text(name, description),
            )
        )

    return entries


def find_matching_folder(text: str, index: list[RegistryEntry]) -> str | None:
    """Find an existing task folder with similar content."""
    if not text:
        return None

    best_score = 0
    best_folder = None

    for entry in index:
        if not entry.comparison_text:
            continue
        score = fuzz.token_sort_ratio(text, entry.comparison_text)
        if score > best_score:
            best_score = score
            best_folder = entry.folder

    if best_score >= SIMILARITY_THRESHOLD:
        return best_folder
    return None


def to_folder_name(name: str, index: int = 0) -> str:
    """Convert a skill name to a filesystem-safe folder name."""
    folder = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not folder or folder == ".":
        folder = f"skill-{index}"
    return folder


def write_skill_yaml(
    folder: str, skill_file: SkillFile, metadata: dict[str, str]
) -> str:
    """Write a new skill YAML entry to the registry."""
    target_dir = REGISTRY_DIR / folder
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{skill_file.owner}-{skill_file.repo}-{skill_file.skill_dir}.yaml"
    filepath = target_dir / filename

    entry_id = f"{skill_file.owner}-{skill_file.repo}-{skill_file.skill_dir}"
    raw_desc = metadata.get("description", "")
    description = re.sub(r"\s+", " ", raw_desc).strip()

    entry = {
        "id": entry_id,
        "description": description,
        "url": skill_file.raw_url,
        "folder_url": skill_file.folder_url,
        "repo": f"{skill_file.owner}/{skill_file.repo}",
        "skill_dir": skill_file.skill_dir,
        "added_at": date.today().isoformat(),
    }
    if skill_file.skill_filename != "SKILL.md":
        entry["skill_filename"] = skill_file.skill_filename

    with open(filepath, "w") as f:
        yaml.dump(entry, f, default_flow_style=False, sort_keys=False)

    logger.info("Wrote %s", filepath.relative_to(REPO_ROOT))
    return str(filepath)


def create_pr(new_files: list[str], token: str) -> None:
    """Create a git branch, commit new files, and open a PR."""
    if not new_files:
        logger.info("No new skills found — skipping PR creation.")
        return

    today = date.today().isoformat()
    branch = f"bot/skill-update-{today}"

    subprocess.run(
        ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
        check=True,
        cwd=REPO_ROOT,
    )
    subprocess.run(
        ["git", "config", "user.name", "github-actions[bot]"],
        check=True,
        cwd=REPO_ROOT,
    )

    result = subprocess.run(
        ["git", "checkout", "-b", branch],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        subprocess.run(["git", "checkout", branch], check=True, cwd=REPO_ROOT)

    for filepath in new_files:
        subprocess.run(["git", "add", filepath], check=True, cwd=REPO_ROOT)

    commit_msg = f"chore(registry): add {len(new_files)} new skill entries"
    subprocess.run(["git", "commit", "-m", commit_msg], check=True, cwd=REPO_ROOT)
    subprocess.run(
        ["git", "push", "-u", "origin", branch],
        check=True,
        cwd=REPO_ROOT,
        env={**os.environ, "GITHUB_TOKEN": token},
    )

    body_lines = [
        "## New Skill Entries",
        "",
        f"This automated PR adds **{len(new_files)}** new skill(s) to the registry.",
        "",
    ]

    by_folder: dict[str, list[str]] = {}
    for filepath in new_files:
        rel = Path(filepath).relative_to(REPO_ROOT)
        folder = rel.parent.name
        by_folder.setdefault(folder, []).append(rel.name)

    for folder in sorted(by_folder):
        body_lines.append(f"### {folder}")
        for fname in sorted(by_folder[folder]):
            body_lines.append(f"- `{fname}`")
        body_lines.append("")

    body_lines.append("Please review the entries and merge if they look correct.")

    subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            f"chore(registry): add {len(new_files)} new skill entries",
            "--body",
            "\n".join(body_lines),
            "--head",
            branch,
        ],
        check=True,
        cwd=REPO_ROOT,
        env={**os.environ, "GH_TOKEN": token, "GITHUB_TOKEN": token},
    )

    logger.info("PR created for branch %s", branch)


@retry()
def _fetch_skill_content(repo, path: str) -> str:
    content = repo.get_contents(path)
    if isinstance(content, list):
        content = content[0]
    return content.decoded_content.decode()


def _scan_source(source: Source, github: Github) -> list[SkillFile]:
    """Scan a single source repo, returning discovered skill files.

    Isolates per-source failures so one broken repo doesn't abort the run.
    """
    try:
        skills = find_skill_files(source, github)
        logger.info(
            "Found %d skill(s) in %s/%s", len(skills), source.owner, source.repo
        )
        return skills
    except GithubException as exc:
        logger.error(
            "Failed to scan %s/%s: %s", source.owner, source.repo, exc
        )
        return []
    except Exception as exc:
        logger.error(
            "Unexpected error scanning %s/%s: %s", source.owner, source.repo, exc
        )
        return []


def _fetch_skill_with_content(
    skill: SkillFile, github: Github
) -> tuple[SkillFile, dict[str, str]] | None:
    """Fetch a single skill's content and extract metadata.

    Returns None on failure so one broken file doesn't abort the run.
    """
    try:
        repo = github.get_repo(f"{skill.owner}/{skill.repo}")
        content = _fetch_skill_content(repo, skill.path)
        metadata = extract_metadata(content)
        return skill, metadata
    except GithubException as exc:
        logger.error(
            "Failed to fetch %s/%s/%s: %s",
            skill.owner, skill.repo, skill.skill_dir, exc,
        )
        return None
    except Exception as exc:
        logger.error(
            "Unexpected error fetching %s/%s/%s: %s",
            skill.owner, skill.repo, skill.skill_dir, exc,
        )
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan source repos for SKILL.md files and update the registry."
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        default=False,
        help="Re-process already registered skills (fetch from GitHub and update YAML). "
             "Without this flag, only new/unregistered skills are processed.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN environment variable is required")

    github = Github(token)
    sources = load_sources()
    index = build_registry_index()

    # --- Phase 1: Scan all sources in parallel ---
    logger.info("Phase 1: Scanning %d sources (%d workers)...", len(sources), MAX_SCAN_WORKERS)
    all_skills: list[SkillFile] = []

    with ThreadPoolExecutor(max_workers=MAX_SCAN_WORKERS) as pool:
        futures = {
            pool.submit(_scan_source, source, github): source
            for source in sources
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                skills = future.result()
                all_skills.extend(skills)
            except Exception as exc:
                logger.error("Unhandled error for %s/%s: %s", source.owner, source.repo, exc)

    logger.info("Discovered %d total skill file(s) across all sources", len(all_skills))

    # Filter out already-registered skills unless --refresh is set
    if args.refresh:
        logger.info("--refresh enabled: re-processing all %d discovered skill(s)", len(all_skills))
        to_process = all_skills
    else:
        to_process = []
        for skill in all_skills:
            if already_registered(skill.owner, skill.repo, skill.skill_dir):
                logger.info("Already registered: %s/%s/%s", skill.owner, skill.repo, skill.skill_dir)
            else:
                to_process.append(skill)
        logger.info("%d new skill(s) to process", len(to_process))

    if not to_process:
        logger.info("No skills to process — nothing to do.")
        return

    # --- Phase 2: Fetch content for skills in parallel ---
    logger.info("Phase 2: Fetching content for %d skills (%d workers)...", len(to_process), MAX_FETCH_WORKERS)
    fetched: list[tuple[SkillFile, dict[str, str]]] = []

    with ThreadPoolExecutor(max_workers=MAX_FETCH_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_skill_with_content, skill, github): skill
            for skill in to_process
        }
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                fetched.append(result)

    logger.info("Successfully fetched %d / %d skill(s)", len(fetched), len(to_process))

    # --- Phase 3: Register skills sequentially (folder matching depends on updated index) ---
    logger.info("Phase 3: Registering %d skill(s)...", len(fetched))
    new_files: list[str] = []

    for skill, metadata in fetched:
        text = build_comparison_text(metadata["name"], metadata["description"])
        folder = find_matching_folder(text, index) or to_folder_name(
            metadata["name"] or skill.skill_dir, len(new_files)
        )
        filepath = write_skill_yaml(folder, skill, metadata)
        new_files.append(filepath)

        index.append(
            RegistryEntry(
                folder=folder,
                filename=Path(filepath).name,
                name=metadata["name"],
                description=metadata["description"],
                comparison_text=text,
            )
        )

    create_pr(new_files, token)


if __name__ == "__main__":
    main()
