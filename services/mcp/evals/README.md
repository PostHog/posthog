# MCP agent-experience evals

The objective function for improving the MCP server: a fixed benchmark of agent tasks, sampled from real usage, that can be scored against a live MCP server. A change to a tool description, schema, or handler "improves the MCP" only if these scores say so.

Two consumers:

- **Regression protection** — run before/after any change to tool descriptions, schemas, or the catalog.
- **The improve-my-mcp campaign** — an autoresearch-style loop that proposes a change, re-runs the affected benchmark slice, and only keeps changes that measurably help. Every campaign PR carries before/after scores from this harness as evidence.

## Layout

- `benchmark/tasks.yaml` — the task set (v0). Each task is a realistic agent goal with the tools a competent agent should reach for.
- `benchmark/schema.ts` — zod schema, loader, and types. `tests/evals/benchmark.test.ts` validates the fixtures against the schema and the live tool catalog, so a tool rename or removal fails CI here instead of silently invalidating the benchmark.

## Task format

```yaml
- id: flags-list-active # kebab-case, unique
  category: feature-flags # see TASK_CATEGORIES in schema.ts
  intent: 'List all our active feature flags.' # what the agent is asked, phrased like a real request
  expected_tools: [feature-flag-get-all] # what a competent agent should call
  acceptable_tools: [execute-sql] # also fine; no tool-selection penalty
  success_criteria: "Returns the project's active flags by key." # pass condition for the agent-mode judge
  probe: # optional: deterministic call, no LLM needed
    tool: feature-flag-get-all
    args: {}
    max_ms: 15000
```

## Modes

**Probe mode** (deterministic, no LLM): executes each task's `probe` against a live server and validates schemas, latency, and error responses for every referenced tool. Probes must reference read-only tools — the fixture test enforces `readOnlyHint`, and the runner refuses anything else, so a bad fixture cannot mutate project data.

**Agent mode** (LLM): replays each `intent` through an agent loop against the live server, then scores task success against `success_criteria` (LLM judge) and tool selection against `expected_tools`/`acceptable_tools`.

Scores per run: task success rate, tool-selection accuracy, schema-validation failure count, tool error rate, retries per task, latency p50/p95, tokens per task.

## Authoring rules

- Sample intents from real usage (`$mcp_intent` clusters, `query-mcp-tool-sample-intents`) but **paraphrase — never paste customer text verbatim**, and never include PII.
- Keep the task set stable within a campaign: scores are only comparable across runs of the same benchmark version. Bump `version` on breaking changes to the set.
- Weight new tasks toward observed pain: high-error tools, discoverability misses (intents where agents picked the wrong tool), and multi-step chains (resolve id → act).
- A task must be achievable in a seeded demo project — don't write tasks that depend on one specific production dataset.
