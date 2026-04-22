# LLM analytics agent guide

Repo-wide conventions live in [`../../AGENTS.md`](../../AGENTS.md) — kea over hooks, generated
API over `api.get`, `ph_scoped_capture` in Celery, etc. Read that first.

This file is only for rules that are specific to `products/llm_analytics/`
(and to the query runners in `posthog/hogql_queries/ai/`).

**If you don't know the folder yet, read [README.md](./README.md) first**
for the directory map. Skip it if you already know where things live —
it's orientation, not a rulebook.

## Update both query runners together

`LLMTrace` and `LLMTraceEvent` are built by two parallel query runners:

- `posthog/hogql_queries/ai/trace_query_runner.py` (single trace read)
- `posthog/hogql_queries/ai/traces_query_runner.py` (list of traces)

Both define their own `_map_trace` and `_map_event`. Neither imports
from the other. Any time you add, remove, or rename a field on
`LLMTrace` or `LLMTraceEvent`, or change how an event is shaped into
either, **change both runners in the same PR** and cover the change in
`posthog/hogql_queries/ai/test/`. The type checker will not catch drift
here.

The same rule applies to routing via `ai_events` vs `events`. If one
runner adopts a new code path, the other needs the matching change so
single-trace and list reads don't diverge.

## Product docs go under `docs/`

Rollout plans, migration plans, and product ADRs belong in
`products/llm_analytics/docs/`, not at the product root.

## See also

- [docs/ai-events-table-rollout.md](./docs/ai-events-table-rollout.md) — ongoing `ai_events` ClickHouse table rollout.
