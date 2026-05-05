# query_performance_ai

Local-only coordinator that hands prod ClickHouse slow queries to a sandboxed agent and asks it to optimise them.

The agent is [pi-coding-agent](https://pi.dev) running the [pi-autoresearch](https://github.com/davebcn87/pi-autoresearch) extension under our bundled `clickhouse-autoresearch-campaign` skill (`sandboxed_autoresearch_agent/pi_plugin/`).

## Prereqs

- `ANTHROPIC_API_KEY` exported in your shell or set in the repo `.env` (Claude Code's gateway token is intentionally NOT used).
- Docker Desktop running (macOS only — the coordinator hard-fails on other platforms).

## What happens when you run it

1. Fetch slow queries from Metabase's prod `system.query_log` (filtered hard to `ai_data_processing_approved = true` — we only ever feed the agent queries that the customer explicitly approved for AI analysis).
2. Open a token-gated HTTP server on localhost.
3. Spawn one Docker sandbox per query. Each sandbox clones this repo's branch from origin, locks down its network with iptables, and runs pi-coding-agent.
4. The agent submits candidate SQL through the coordinator's `/v1/run`; the coordinator forwards each query to the configured backend.
5. Artifacts (best.sql, metrics, lane / hypothesis notes) are harvested to `data/runs/<query_id>_<run_id>/` and the sandbox is destroyed.

## Backends

```bash
# Replay candidates against a Metabase-fronted test cluster:
python -m products.query_performance_ai.orchestrator.coordinator \
    --target test_cluster --metabase-region us \
    --query-log-database-id 142 --test-cluster-database-id 146 \
    --team-id 2 --max-queries 5
# Requires `hogli metabase:login --region us` first.

# Replay candidates against your local dev ClickHouse:
python -m products.query_performance_ai.orchestrator.coordinator --target local
```

`--target` decides where candidate SQL runs. Slow queries are always sourced from Metabase regardless; only the execution destination differs.

## Smoke test

```bash
python -m products.query_performance_ai.orchestrator.coordinator --target local --test-query
```

`--test-query` skips Metabase and feeds `SELECT 1, sleep(1)` as the campaign SQL. End-to-end smoke — the agent should drop the `sleep` within a couple of iterations.

## Privacy

The Metabase fetch in `orchestrator/slow_queries.py` filters to `ai_data_processing_approved = true` in `log_comment`. This is a hard SQL predicate, not a runtime check; no flag bypasses it. `--test-query` runs a synthetic constant, not a real customer query.
