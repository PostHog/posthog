# LLM Analytics skills

Agent skills for the LLM Analytics product.
Built by `hogli build:skills` and installed into sandbox containers for background agents.
Also available to Claude Code / Codex via `hogli sync:skill`.

## Skills

- **exploring-llm-traces** — how to query, inspect, and debug LLM traces via MCP tools.
  Covers the `$ai_*` event schema, content detail levels, and step-by-step debugging workflows.

## Adding a new skill

```bash
hogli init:skill -- --product llm_analytics --name my-new-skill
```

See `products/posthog_ai/scripts/build_skills.py` for the build pipeline
and `AGENTS.md` for conventions.

## Local testing

```bash
hogli sync:skill -- --name exploring-llm-traces
```

This copies the built skill to `.agents/skills/` for Claude Code to discover.
