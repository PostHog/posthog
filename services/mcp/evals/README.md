# MCP agent-experience evals

The objective function for improving the MCP server: a fixed benchmark of agent tasks, sampled from real usage, that can be scored against a live MCP server. A change to a tool description, schema, or handler "improves the MCP" only if these scores say so.

Two consumers:

- **Regression protection** — run before/after any change to tool descriptions, schemas, or the catalog.
- **The improve-my-mcp campaign** — an autoresearch-style loop that proposes a change, re-runs the affected benchmark slice, and only keeps changes that measurably help. Every campaign PR carries before/after scores from this harness as evidence.

## Layout

- `benchmark/tasks.yaml` — the task set (v2). Each task is a realistic agent goal with the tools a competent agent should reach for, plus a `fixtures` block naming the entities a run needs in place.
- `benchmark/schema.ts` — zod schema, loader, and types. `tests/evals/benchmark.test.ts` validates the fixtures against the schema and the live tool catalog, so a tool rename or removal fails CI here instead of silently invalidating the benchmark.
- `runner/probe.ts` — the probe runner. See [Probe mode](#probe-mode).
- `runner/results.ts` — result types and score aggregation for probe runs, unit-tested in `tests/evals/results.test.ts`.
- `runner/seed.ts` — writes the `fixtures` block to the target project. See [Seeding](#seeding).

## Task format

```yaml
- id: flags-list-active # kebab-case, unique
  category: feature-flags # see TASK_CATEGORIES in schema.ts
  intent: 'List all our active feature flags.' # what the agent is asked, phrased like a real request
  expected_tools: [feature-flag-get-all] # what a competent agent should call
  acceptable_tools: [execute-sql] # also fine; no tool-selection penalty
  success_criteria: "Returns the project's active flags by key." # pass condition for an agent run; no runner reads it
  probe: # optional: deterministic call, no LLM needed
    tool: feature-flag-get-all
    args: {}
    max_ms: 15000
```

## Probe mode

Probe mode is the only runner in this directory. It is deterministic and uses no LLM:

```bash
LIVE_MCP_URL=http://localhost:9876 LIVE_MCP_TOKEN=phx_... \
  pnpm exec tsx evals/runner/probe.ts [--out score.json]
```

It checks that the server advertises every tool a task requires, then executes each task's `probe` and records its status and latency.
Probes must reference read-only tools — the fixture test enforces `readOnlyHint`, and the runner refuses any tool the live server does not advertise as read-only, so a bad fixture cannot mutate project data.

The summary reports missing tools, probes passed and failed, and latency p50/p95.
The exit code is non-zero when a required tool is missing or a probe fails.

No agent-mode runner or LLM judge exists yet.
`intent`, `expected_tools`, `acceptable_tools`, and `success_criteria` describe the task for an agent run, but no code here scores them.

## Seeding

Tasks that create or change entities need those entities in a known state before an agent runs them.
`fixtures` in `tasks.yaml` declares that state, and `runner/seed.ts` writes it:

```bash
LIVE_POSTHOG_URL=http://localhost:8000 LIVE_MCP_TOKEN=phx_... \
  pnpm exec tsx evals/runner/seed.ts [--project 12345]
```

Run it before every agent run against the benchmark.
It is idempotent over the keys it owns: it rewrites every flag in `fixtures.feature_flags` and clears the keys in `fixtures.absent_feature_flags`, so those tasks start a second run where they started the first.
`flag-create-routes-to-experiment` is the exception. The agent picks the key of the flag its experiment manages, so the seeder cannot name that key in `absent_feature_flags`, and the experiment and flag from an earlier run are still there on the next one. Delete them by hand when a rerun needs a clean project.
Probe mode needs no seeding — probes are read-only.

Two things to get right:

- **Seed the project the MCP session acts on.** Without `--project` the seeder uses the token's current project. Seeding one project while the run scores another looks exactly like a tool-selection regression.
- **Give each mutating task its own fixture.** Two tasks sharing one flag make the run order-dependent: whichever runs first decides what the next one starts from. `tests/evals/benchmark.test.ts` asserts every fixture key is named in exactly one intent, which catches both a shared fixture and an orphaned one.

The seeder talks to the REST API, not to the MCP server, so the tools under test are not also what builds the state they are measured against.

## Authoring rules

- Sample intents from real usage (`$mcp_intent` clusters, `query-mcp-tool-sample-intents`) but **paraphrase — never paste customer text verbatim**, and never include PII.
- Keep the task set stable within a campaign: scores are only comparable across runs of the same benchmark version. Bump `version` on breaking changes to the set.
- Weight new tasks toward observed pain: high-error tools, discoverability misses (intents where agents picked the wrong tool), and multi-step chains (resolve id → act).
- A task must be achievable in a seeded demo project — don't write tasks that depend on one specific production dataset.
