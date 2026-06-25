# Contributing to the TrueFoundry Skills Registry

This registry is **automated**. You don't hand-write skill entries — you just
point us at a GitHub repo, and a GitHub Action scans it for `SKILL.md` files,
classifies each skill, and adds it to the catalog.

## The Only Way to Contribute

**Add the repo link to [`sources.yaml`](sources.yaml).** That's it.

- If the skill already lives in a public repo, add that repo's URL.
- If you wrote a skill yourself, push your `SKILL.md` to a public repo and add
  that repo's URL.

Once your change is merged, the GitHub Action picks up the new source, discovers
its skills, and writes everything into the registry automatically.

## How to Add a Source

1. Fork this repository.
2. Add your repo to [`sources.yaml`](sources.yaml). Pick the line that matches
   where the `SKILL.md` files live:

   **`SKILL.md` at the repo root:**

   ```yaml
   - url: https://github.com/owner/my-skill
   ```

   **Skills inside a folder** (each subfolder with a `SKILL.md` becomes an entry):

   ```yaml
   - url: https://github.com/owner/my-skills
     skills_path: skills/
   ```

   **A different filename** (not `SKILL.md`):

   ```yaml
   - url: https://github.com/owner/my-skill
     skills_path: skill/
     skill_filename: mem.md
   ```

   Add `is_official: true` only for first-party/vendor repos.

3. Open a pull request. Title it something like
   `chore(sources): add owner/repo`.

You're done — no need to run anything locally.

## Authoring Your Own Skill

A skill is just a folder with a `SKILL.md` file. Keep the YAML frontmatter filled
in so it gets a clean name and description in the catalog:

```markdown
---
name: skill-name
description: One-sentence description of what this skill does and when to use it.
---

# Skill Name

What the skill does and how to use it, with a couple of real examples.
```

Push that to a public repo, then add the repo URL to `sources.yaml` as above.

## Tips for a Good Skill

- Solve a **real** problem, based on actual usage.
- Write a clear, specific `description` — it drives the auto-assigned category and tags.
- Include practical examples.
- Confirm before destructive operations.
- Credit the original author or source where applicable.

## Registry Entry Format

You never write these by hand — the pipeline generates one YAML file per skill at
`registry/{owner}-{repo}/{owner}-{repo}-{skill-dir}.yaml`:

```yaml
id: anthropics-skills-algorithmic-art
display_name: Algorithmic Art
description: Creating algorithmic art using p5.js with seeded randomness ...
authors:
  - anthropics
is_official: true
tags:
  - generative-art
  - p5js
  - creative-coding
category: creative
source:
  path: /skills/algorithmic-art
  repo: anthropics/skills
metadata:
  stars: 149805
added_at: "2026-06-05"
```

- **Filename** `{owner}-{repo}-{skill_dir}.yaml` is globally unique; it's also the
  dedupe key, so a skill is "known" if that stem exists in any folder.
- **One folder per source repo** keeps every source's skills together.
- **`metadata.stars`** records the source repo's GitHub star count and drives the
  ordering of `dist/ai-skills.json`.

## Questions?

Open an [issue](https://github.com/truefoundry/tfy-skills-repo/issues) if you need
help adding a source.
