# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> `AGENTS.md` documents coding style and commit/PR conventions in prose — read it for those. This file covers the essential commands plus the architecture and non-obvious behaviors that only emerge from reading multiple files together.

## Commands

```bash
uv sync --locked                                          # install locked deps (Python 3.12)
GITHUB_TOKEN=<token> uv run python scripts/update.py      # scan sources, write entries, open a PR
uv run python scripts/lint_registry.py                    # validate all registry YAML (exit 1 on issues)
uv run python scripts/lint_registry.py --fix              # auto-fix whitespace/newline issues in place
uv run python scripts/lint_registry.py registry/foo/x.yaml  # lint a single file (the single-unit analog — no test suite)
./scripts/validate.sh                                     # validate all registry YAML against schema.cue (needs `cue`: brew install cue-lang/tap/cue)
uv run python scripts/build_unified_json.py               # collect registry/ → dist/ai-skills.json
uv run python scripts/backfill_categories.py              # fill category/tags for entries still at `category: none` (needs TFY_API_KEY)
git config core.hooksPath .githooks                       # enable the staged-registry pre-commit lint hook
```

## What this repo is

A **generator and its generated output**, not a runtime service. The scripts under `scripts/` hold all the real logic; everything under `registry/` (700+ YAML files) is data the pipeline produces. When making changes, distinguish between editing the generator (`scripts/`) and editing generated entries (`registry/`) — they have different review implications.

The pipeline scans configured GitHub repos for `SKILL.md` files, extracts metadata, **classifies each skill into a `category` + `tags` via an LLM** (`classify.py`), groups each new skill into a task folder, and opens a PR. It is agent-agnostic: any repo using `SKILL.md` files works (Claude, Cursor, custom agents).

The scripts: `update.py` (scan → write → PR), `lint_registry.py` (field-level validation), `classify.py` (LLM category/tag assignment), `backfill_categories.py` (retro-classify existing entries), `build_unified_json.py` (registry → `dist/ai-skills.json`), and `validate.sh` (CUE schema validation).

## Data flow (one pass of `scripts/update.py`)

`load_sources()` → for each source, `find_skill_files()` walks the repo via the GitHub API → `already_registered()` skips known skills → `_fetch_skill_content()` + `extract_metadata()` → `classify()` assigns `category`/`tags`/refined `display_name` → `find_matching_folder()` picks the destination → `write_skill_yaml()` writes the entry → `create_pr()` branches, commits, pushes, and opens a PR with `gh`.

`classify()` (`classify.py`) calls the TrueFoundry AI Gateway (`bedrock/global.anthropic.claude-sonnet-4-6`, needs `TFY_API_KEY` in `.env`); the category is constrained to `lint_registry.VALID_CATEGORIES`. If the call fails or the key is missing, the entry is written with `category: none` and empty `tags` — `backfill_categories.py` later fills those in idempotently (only touches `category: none` entries, writing each chunk back as it goes).

The in-memory `index` (list of `RegistryEntry`) is built once from disk at startup and **appended to as new skills are written in the same run**, so later skills in a run can group against earlier ones from the same run.

## Non-obvious behaviors (the things that bite)

- **Dedupe key is the filename stem, not the folder.** `already_registered()` globs `registry/**/{owner}-{repo}-{skill_dir}.yaml` recursively. A skill is "known" if that stem exists in *any* folder. Filenames are globally unique across the registry — folders are just grouping.

- **Similarity grouping** (`find_matching_folder`): compares `"{name} {description}"` against every existing entry via `rapidfuzz.token_sort_ratio`. Score `>= SIMILARITY_THRESHOLD` (75) → reuse that entry's folder; otherwise `to_folder_name()` creates a new lowercase-dashed folder from the skill name. Changing the threshold reshapes how future skills cluster.

- **Metadata extraction is a 3-tier fallback** (`extract_metadata`): YAML frontmatter `name`/`description` first; then a `# Skill: ...` heading for the name; then the first non-heading line as the description. Many `SKILL.md` files in the wild only have a heading, so the fallbacks matter.

- **`skills_path` (singular) vs `skills_paths` (plural)** in `sources.yaml`: singular is one scan root (defaults to `"/"` = `SKILL.md` at repo root); plural is multiple roots with no shared parent. `load_sources()` normalizes both into the canonical `skills_paths` list and appends trailing slashes. `"/"` triggers a single root-file lookup; any other path triggers a recursive `_walk_contents` tree walk.

- **Descriptions get normalized twice.** `write_skill_yaml` collapses whitespace on write, and `lint_registry.py` re-normalizes (`_normalize_description`) to undo YAML block-scalar folding artifacts. If you change one, keep them consistent — divergence causes lint churn on otherwise-untouched files.

## Validation

There is no unit-test suite. Two complementary gates guard `registry/`:

- **`lint_registry.py`** (field-level) enforces required fields — `id`, `display_name`, `description`, `authors`, `is_official`, `tags`, `category`, `source` (with `source.repo`/`source.path`), `metadata`, `added_at` — checks `category` against `VALID_CATEGORIES`, flags description whitespace artifacts, and (with `--fix`) rewrites files in a fixed field order.
- **`validate.sh`** (structural) runs `cue vet` against `schema.cue` (`#Skill`), enforcing types and the `#Tag` shape. Requires `cue` (`brew install cue-lang/tap/cue`).

The linter runs in three places: the `.githooks/pre-commit` hook on staged registry YAML, the `Lint Registry` CI workflow (`lint.yml`) on any PR/push touching `registry/**/*.yaml`, and manually. `validate.sh` runs in `sync.yml` (see below) and manually.

## Pipeline & auth

Three workflows:

- **`pipeline.yml`** — weekly (Sunday 00:00 UTC) or manual dispatch; runs `update.py` to scan sources and open a PR.
- **`lint.yml`** ("Lint Registry") — runs `lint_registry.py` on PRs/pushes touching `registry/**/*.yaml`.
- **`sync.yml`** — on push to `main`: lint → CUE-validate (`validate.sh`) → `build_unified_json.py` → upload `dist/ai-skills.json` to S3 (`s3://.../llm-gateway/v2/devtest/ai-skills.json`, via OIDC role assume).

`create_pr()` shells out to `git` and `gh`, so both must be authenticated; the script reads `GITHUB_TOKEN` from the environment (required — it exits if unset) and passes it to `git push` and `gh` as `GH_TOKEN`/`GITHUB_TOKEN`. For local runs, use a least-privilege token (`public_repo` for public-only scans). Classification additionally needs `TFY_API_KEY` in `.env`; without it, `update.py` still runs and writes `category: none`.
