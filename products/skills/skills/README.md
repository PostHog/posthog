# Skills

Agent skills for the Skills product — managing agent skills stored in PostHog.
Built by `hogli build:skills` and installed into sandbox containers for background agents.
Also available to Claude Code / Codex via `hogli sync:skill`.

## Skills

- **skills-store** — discover and use shared team skills stored in PostHog.
- **working-with-skills** — best-practice playbook for agents managing skills via the
  `skill-*` MCP tools: decision tree for picking the right write primitive,
  progressive disclosure discipline, large multi-file workflows, concurrency, and
  common pitfalls.

## Adding a new skill

```bash
hogli init:skill -- --product skills --name my-new-skill
```

See `products/posthog_ai/scripts/build_skills.py` for the build pipeline.

## Local testing

```bash
hogli sync:skill -- --name working-with-skills
```

This copies the built skill to `.agents/skills/` for Claude Code to discover.
