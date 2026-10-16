# MCP evals

A benchmark of agent tasks for the PostHog MCP server, a script that runs each task's probe call against a live server, and a script that seeds the feature flags some tasks need.

## Layout

- `benchmark/tasks.yaml` — the task set, plus a `fixtures` block of feature flags that some tasks act on.
- `benchmark/schema.ts` — the zod schema and loader for `tasks.yaml`.
- `runner/probe.ts` — runs each task's `probe` against a live MCP server. See [Probe runner](#probe-runner).
- `runner/results.ts` — the result types and summary for a probe run.
- `runner/seed.ts` — writes the fixture flags to a PostHog project. See [Seeding](#seeding).

`tests/evals/benchmark.test.ts` runs in CI and checks `tasks.yaml`. Among other checks, it fails when a task names a tool that is not in the MCP tool catalog, when a probe uses a tool that is not read-only, or when a fixture flag is named in no task intent or in more than one.

## Task format

```yaml
- id: flags-list-active # kebab-case, unique
  category: feature-flags # one of TASK_CATEGORIES in schema.ts
  intent: 'List all our active feature flags.' # the request, phrased like a real user's
  expected_tools: [feature-flag-get-all] # tools a competent agent should call
  acceptable_tools: [execute-sql] # other tools that are also a reasonable path
  success_criteria: "Returns the project's active flags by key." # what a correct answer does
  probe: # optional: one read-only call the probe runner makes
    tool: feature-flag-get-all
    args: {}
    max_ms: 15000
```

The probe runner checks `expected_tools` and runs `probe`. No script here scores `intent` or `success_criteria`.

## Probe runner

Run from `services/mcp/`:

```bash
LIVE_MCP_URL=http://localhost:9876 LIVE_MCP_TOKEN=phx_... \
  pnpm exec tsx evals/runner/probe.ts [--out score.json]
```

It connects in tools mode, then:

1. Lists the tools the server advertises, and reports each task's `expected_tools` or `probe` tool that is missing.
2. Runs each task's `probe` call and records its status and latency.
   It refuses a probe whose tool the server does not advertise as read-only, so a bad fixture cannot change project data.
3. Prints a summary: missing tools, probes passed and failed, and latency p50/p95. `--out` also writes it as JSON.

The exit code is non-zero when a tool is missing or a probe fails.

## Seeding

Some tasks ask an agent to create or change feature flags.
The `fixtures` block lists those flags, and `runner/seed.ts` puts them in a known state.
Run from `services/mcp/`:

```bash
LIVE_POSTHOG_URL=http://localhost:8000 LIVE_MCP_TOKEN=phx_... \
  pnpm exec tsx evals/runner/seed.ts [--project 12345]
```

- It creates or updates every flag in `fixtures.feature_flags`, and soft-deletes every key in `fixtures.absent_feature_flags`. Running it again resets those flags.
- `flag-create-routes-to-experiment` is the exception. The agent picks the key of the flag its experiment manages, so the seeder cannot reset it. Delete that experiment and flag by hand when you need a clean project.
- It writes through the REST API, not the MCP server, so the tools under test do not build their own starting state.
- Without `--project` it seeds the token's current project. Seed the project the MCP session acts on.
- The token needs `feature_flag:write`, plus `user:read` when `--project` is omitted.
- The exit code is non-zero when any fixture could not be written.

Probes are read-only, so the probe runner needs no seeding.

## Authoring rules

- Sample intents from real usage (`$mcp_intent` clusters, `query-mcp-tool-sample-intents`) but **paraphrase — never paste customer text verbatim**, and never include PII.
- Results are only comparable across runs of the same benchmark `version`. Bump it on breaking changes to the set, together with the version literal in `schema.ts`.
- Weight new tasks toward observed pain: high-error tools, discoverability misses (intents where agents picked the wrong tool), and multi-step chains (resolve id → act).
- Give each task that changes a flag its own fixture flag, so the result does not depend on task order. The fixture test enforces this.
- A task must be achievable in a seeded demo project — don't write tasks that depend on one specific production dataset.
