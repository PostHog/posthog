# PostHog AI skills

Agent skills owned by PostHog AI.
Built by `hogli build:skills` and installed into sandbox containers for background agents.
Also available to Claude Code / Codex via `hogli sync:skill`.

This directory also happens to host the build pipeline for _every_ product's skills — see [Build pipeline](#build-pipeline) below.

## Skills

- **querying-posthog-data** — required reading before writing any HogQL/SQL. Indexes ~60 references covering the `system.*` table schemas, HogQL's differences from ClickHouse SQL, available functions, and the semantic layer (canonical metrics in `system.information_schema.metrics`).
- **managing-subscriptions** — scheduled email, Slack, and webhook deliveries of insight or dashboard snapshots, optionally with an AI-written summary. Covers subscriptions vs alerts, prompt subscriptions, and the AI-consent and quota gates.
- **auditing-experiments-flags** — health-checks experiments and feature flags for configuration issues, staleness, and best-practice violations, with severity-badged findings.
- **writing-simplified-technical-english** — writes English a reader cannot misread, based on ASD-STE100. Used at runtime by Signals and Review Hog for any prose an agent produces that someone else acts on.
- **checking-deploy-timing** — determines when a PostHog code change reached an environment, by reading the hidden `GIT` deploy annotations and correlating them with the merge commit on GitHub. Internal staff only.

## Adding a new skill

```bash
hogli init:skill -- --product posthog_ai --name my-new-skill
```

Read [`/writing-skills`](../../../.agents/skills/writing-skills/SKILL.md) first — it carries the naming, description, and structure rules, and the [handbook guide](../../../docs/published/handbook/engineering/ai/writing-skills.md) has the full version.

Two things worth knowing before you add one:

- **Skill count is a budgeted, shared resource.** Agents pick from a list of _all_ skill descriptions, and many harnesses truncate that list. More depth belongs in an existing skill's `references/`, not in a new skill.
- **These skills ship to users.** They are packaged into `dist/skills.zip` and published as a GitHub release. Internal, repo-only guidance for engineers working in this monorepo belongs in [`.agents/skills/`](../../../.agents/skills/) instead.

## Build pipeline

Skills live in `products/*/skills/` as Markdown or Jinja2 templates. The build renders them into `products/posthog_ai/dist/skills/` (human-readable) and packages them into `dist/skills.zip`. Both are gitignored — CI builds the ZIP from source and publishes it as a GitHub release.

```bash
hogli build:skills          # Build skills to dist/skills/ and dist/skills.zip
hogli build:skills --list   # List discovered skills
hogli lint:skills           # Validate skill sources without rendering (syntax, frontmatter, depth, tool references)
hogli init:skill --product <product> --name <name>       # Scaffold a new skill
hogli init:skill --product <product> --name <name> --j2  # Scaffold as Jinja2 template
```

`lint:skills` also cross-checks the MCP tool and skill names you reference in prose against the real registries, so a renamed tool fails the lint instead of misleading an agent.

### Local testing

```bash
hogli sync:skill -- --name <skill-name>     # Copy the built skill into .agents/skills/ for Claude Code
hogli unsync:skill -- --name <skill-name>   # Remove it again
```

### Workflow

1. Edit skill sources in `products/*/skills/`
2. Run `hogli lint:skills`, then `hogli sync:skill` to try it in a real agent session
3. Push to master — CI builds the ZIP and creates a GitHub release (`agent-skills-latest` + versioned)

The pipeline itself lives in [`products/posthog_ai/scripts/build_skills.py`](../scripts/build_skills.py).
