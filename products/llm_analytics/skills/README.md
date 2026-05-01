# LLM Analytics skills

Agent skills for the LLM Analytics product.
Built by `hogli build:skills` and installed into sandbox containers for background agents.
Also available to Claude Code / Codex via `hogli sync:skill`.

## Skills

- **exploring-llm-traces** — how to query, inspect, and debug LLM traces via MCP tools.
  Covers the `$ai_*` event schema, content detail levels, and step-by-step debugging workflows.
- **exploring-llm-clusters** — how to investigate LLM analytics clustering results,
  compare cluster behavior, compute metrics, and drill into individual traces.
- **exploring-llm-costs** — how to investigate LLM spend: total cost, breakdowns
  by model/provider/user/trace/custom dimension, token and cache economics,
  cost regressions, and materializing cost insights, dashboards, and alerts.
- **exploring-llm-evaluations** — how to manage and investigate LLM analytics
  evaluations (both `hog` and `llm_judge` types), run them on specific generations,
  query individual results, and generate AI-powered summaries of pass/fail/N/A patterns.
- **skills-store** — discover and use shared team skills stored as prompts in PostHog.

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
