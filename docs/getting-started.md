<h1 align="center">Getting Started</h1>

<p align="center">
  How to use a skill in your agent, query the catalog programmatically, and
  author your own skill.
</p>

---

## Contents

- [Use a Skill in Your Agent](#use-a-skill-in-your-agent)
- [Find Skills Programmatically](#find-skills-programmatically)
- [Using the Catalog](#using-the-catalog)
- [Creating Skills](#creating-skills)

## Use a Skill in Your Agent

Most agents read skills from a local directory. For example, with Claude Code:

```bash
mkdir -p ~/.config/claude-code/skills/
cp -r skill-name ~/.config/claude-code/skills/
head ~/.config/claude-code/skills/skill-name/SKILL.md
```

The agent loads the skill automatically and activates it when relevant. Cursor,
Windsurf, Cline, Codex, Gemini CLI, and other agents follow the same open
`SKILL.md` convention — drop the folder where your agent expects skills.

## Find Skills Programmatically

The catalog is a single JSON file you can fetch and filter:

```bash
# Top coding skills in the catalog
jq '[.[] | select(.category == "coding")][:10] | .[].display_name' dist/ai-skills.json
```

## Using the Catalog

[`dist/ai-skills.json`](../dist/ai-skills.json) is the canonical export. Each entry
carries the skill's `id`, `display_name`, `description`, `authors`, `tags`,
`category`, `source` (repo + path), `metadata.stars`, and `added_at`. Entries are
ordered by source-repo stars (descending) so the most popular sources lead and
each source's skills stay grouped together — ideal for powering a search UI, an
agent's skill picker, or a recommendations API.

## Creating Skills

Each skill is a folder with a `SKILL.md` file and optional supporting files:

```
skill-name/
├── SKILL.md          # Required: instructions + YAML frontmatter
├── scripts/          # Optional: helper scripts
├── references/       # Optional: reference docs
└── assets/           # Optional: templates / assets
```

Minimal template:

```markdown
---
name: my-skill-name
description: A clear description of what this skill does and when to use it.
---

# My Skill Name

Detailed description of the skill's purpose and capabilities.

## When to Use This Skill

- Use case 1
- Use case 2

## Instructions

[Detailed instructions for the agent on how to execute this skill]

## Examples

[Real-world examples showing the skill in action]
```

**Best practices:** focus on specific, repeatable tasks; write instructions for
the agent, not the end user; include clear examples and edge cases; confirm
before destructive operations; and document prerequisites. The full guide,
including a richer template, lives in [`CONTRIBUTING.md`](../CONTRIBUTING.md).
