# Skills Registry

An agent-agnostic registry that scans configured GitHub repositories for `SKILL.md` files, generates structured YAML metadata entries grouped by task similarity, and opens a pull request for human review via a weekly GitHub Actions pipeline.

Works with any skill convention — Claude, Cursor, custom agents, or anything else that uses `SKILL.md` files.

## How It Works

1. **Configure sources** in [`sources.yaml`](sources.yaml) with GitHub repo URLs and optional `skills_path`.
2. **Weekly pipeline** (Sunday midnight UTC) or manual dispatch runs [`scripts/update.py`](scripts/update.py).
3. The script scans each source repo for `SKILL.md` files, extracts metadata, and groups new skills into task folders by similarity.
4. A PR is opened with the new registry entries for human review.

## Repository Structure

```
├── sources.yaml              # Configured source repos
├── registry/                 # Generated skill entries (grouped by task)
│   └── {task-folder}/
│       └── {owner}-{repo}-{skill-dir}.yaml
├── scripts/
│   └── update.py             # Scanner and registry updater
├── pyproject.toml            # Python project dependencies
├── uv.lock                   # Locked Python dependencies
└── .github/workflows/
    └── pipeline.yml          # Weekly + manual pipeline
```

## Configuring Sources

Edit [`sources.yaml`](sources.yaml) to add or remove source repositories.

### Multi-skill repos

Each subdirectory under `skills_path` containing a `SKILL.md` becomes a separate registry entry:

```yaml
sources:
  - url: https://github.com/garrytan/gbrain
    skills_path: skills/

  - url: https://github.com/tech-leads-club/agent-skills
    skills_path: packages/skills-catalog/skills/
```

### Whole-repo skills

Omit `skills_path` (defaults to `"/"`) when the repo has a single `SKILL.md` at its root:

```yaml
sources:
  - url: https://github.com/jane/pr-reviewer
    # skills_path defaults to "/" — looks for SKILL.md at repo root
```

### Awesome-list repos (not scannable)

Curated link directories like [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills) and [heilcheng/awesome-agent-skills](https://github.com/heilcheng/awesome-agent-skills) are README-based discovery sources, not skill containers. They contain no `SKILL.md` files and cannot be scanned directly. They may be used in the future to discover new repos to add to `sources.yaml`.

## Registry Entry Format

Each skill is stored as `registry/{task-folder}/{owner}-{repo}-{skill-dir}.yaml`:

```yaml
id: anthropics-claude-code-commit
description: Commit message generator following conventional commits spec
url: https://raw.githubusercontent.com/anthropics/claude-code/main/.claude/skills/commit/SKILL.md
folder_url: https://github.com/anthropics/claude-code/tree/main/.claude/skills/commit
repo: anthropics/claude-code
skill_dir: commit
added_at: "2026-06-05"
```

- **Filename**: `{owner}-{repo}-{skill_dir}.yaml` — globally unique across all sources.
- **Task folders**: New skills are grouped into existing folders when similarity score >= 75 (via `rapidfuzz` token sort ratio), otherwise a new folder is created from the skill name.

## Contributing

### Add a new source repo

1. Fork this repository.
2. Add the repo URL (and `skills_path` if needed) to [`sources.yaml`](sources.yaml).
3. Open a PR with your change.

The weekly pipeline will pick up the new source on its next run and open a separate PR with discovered skills.

### Run locally

```bash
uv sync
GITHUB_TOKEN=<your-token> uv run python scripts/update.py
```

Requires a GitHub personal access token with `repo` scope (or `public_repo` for public repos only).

## Sample Source Repos

| Repo | Type | Scannable |
|------|------|-----------|
| [garrytan/gbrain](https://github.com/garrytan/gbrain) | Multi-skill (`skills/`) | Yes |
| [tech-leads-club/agent-skills](https://github.com/tech-leads-club/agent-skills) | Multi-skill (nested catalog) | Yes |
| [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills) | Awesome-list (links only) | No |
| [heilcheng/awesome-agent-skills](https://github.com/heilcheng/awesome-agent-skills) | Awesome-list (links only) | No |
