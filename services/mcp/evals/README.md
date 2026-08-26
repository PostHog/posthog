# MCP agent-experience evals

The objective function for improving the MCP server: a fixed benchmark of agent tasks, sampled from real usage, that can be scored against a live MCP server. A change to a tool description, schema, or handler "improves the MCP" only if these scores say so.

Two consumers:

- **Regression protection** — run before/after any change to tool descriptions, schemas, or the catalog.
- **The improve-my-mcp campaign** — an autoresearch-style loop that proposes a change, re-runs the affected benchmark slice, and only keeps changes that measurably help. Every campaign PR carries before/after scores from this harness as evidence.

## Layout

- `benchmark/tasks.yaml` — the task set (v1). Each task is a realistic agent goal with the tools a competent agent should reach for.
- `benchmark/schema.ts` — zod schema, loader, and types. `tests/evals/benchmark.test.ts` validates the fixtures against the schema and the live tool catalog, so a tool rename or removal fails CI here instead of silently invalidating the benchmark.
- `runner/probe.ts` — probe mode (see Modes below).
- `runner/agent.ts` — agent mode: drives a real agent loop over the live server and records the tools it reached for.
- `runner/selection.ts` — the tool-selection scoring math, kept pure so `tests/evals/selection.test.ts` can pin it. Campaign keep/discard decisions ride on these numbers.
- `runner/results.ts` — probe-result aggregation, pinned by `tests/evals/results.test.ts`.

## Task format

```yaml
- id: flags-list-active # kebab-case, unique
  category: feature-flags # see TASK_CATEGORIES in schema.ts
  intent: 'List all our active feature flags.' # what the agent is asked, phrased like a real request
  expected_tools: [feature-flag-get-all] # what a competent agent should call
  acceptable_tools: [execute-sql] # answers the task, but off the intended path
  success_criteria: "Returns the project's active flags by key." # pass condition for the agent-mode judge
  probe: # optional: deterministic call, no LLM needed
    tool: feature-flag-get-all
    args: {}
    max_ms: 15000
```

## Modes

**Probe mode** (deterministic, no LLM): executes each task's `probe` against a live server and validates schemas, latency, and error responses for every referenced tool. Probes must reference read-only tools — the fixture test enforces `readOnlyHint`, and the runner refuses anything else, so a bad fixture cannot mutate project data.

**Agent mode** (LLM): replays each `intent` through a real agent loop against the live server, records the tools the agent reached for, and scores that against `expected_tools`/`acceptable_tools`.

```sh
ANTHROPIC_API_KEY=… LIVE_MCP_URL=http://localhost:9876 LIVE_MCP_TOKEN=phx_… \
  pnpm exec tsx evals/runner/agent.ts --out after.json
```

Writes are stubbed by default — the agent is told the call was accepted and nothing is mutated, so a task that expects `insight-create` still scores tool selection.
Pass `--allow-writes` to execute them, and only against a scratch project.
The system prompt says nothing about which tool to prefer: a nudge there would make the benchmark measure the prompt instead of the tool catalog it exists to measure.

### Reading the scores

Agent mode reports two rates, because "answered the task" and "took the intended path" are different questions.

- **`tool_selection_accuracy`** — reached an expected _or_ acceptable tool. This is the discoverability number: it falls when the agent goes somewhere the benchmark doesn't recognize at all.
- **`expected_path_rate`** — reached an _expected_ tool. A task expecting `query-trends` and accepting `execute-sql` scores 1.0 on accuracy either way, but only counts here when the agent takes the typed path. The gap between the two rates is how often the agent substitutes the escape hatch for the tool built for the job.
- **`substitutes`** — which tools stood in for an expected path, most frequent first. Names the substitution rather than leaving it in the aggregate.
- **`sql_reliance`** — how many of the agent's calls were raw SQL, counted only over tasks where SQL was _not_ the expected path. Catches the case both rates miss: six SQL queries followed by one `query-trends` scores a clean `expected`, and this is the number that still moves.

Tasks whose typed tool _errored_ are printed as `NOTE` lines, so a server fault isn't read as the model making a bad pick.

Not yet implemented: the `success_criteria` LLM judge, and per-run token/latency reporting.
`success_criteria` is authored and schema-validated but nothing consumes it, so agent mode currently scores which tools an agent picked — not whether the answer was right.

## Authoring rules

- Sample intents from real usage (`$mcp_intent` clusters, `query-mcp-tool-sample-intents`) but **paraphrase — never paste customer text verbatim**, and never include PII.
- Keep the task set stable within a campaign: scores are only comparable across runs of the same benchmark version. Bump `version` on breaking changes to the set.
- Weight new tasks toward observed pain: high-error tools, discoverability misses (intents where agents picked the wrong tool), and multi-step chains (resolve id → act).
- A task must be achievable in a seeded demo project — don't write tasks that depend on one specific production dataset.
