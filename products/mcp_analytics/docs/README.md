# MCP analytics — product docs

Co-located product docs for `products/mcp_analytics/`.
The layout follows the project convention used by `products/llm_analytics/docs/`: rollout plans, migration plans, PRDs and ADRs live here, not at the product root.

## Contents

### PRDs

- [0001 — MCP analytics v1](./prds/0001-mcp-analytics-v1.md) — scope, surfaces, and success criteria for the first shippable cut of MCP analytics.

### ADRs

- [0001 — Mirror MCP sessions from ClickHouse to Postgres](./adrs/0001-mirror-mcp-sessions-clickhouse-to-postgres.md) — why we maintain a Postgres `MCPSession` table populated by a Temporal aggregate, instead of querying ClickHouse directly from the API.
- [0002 — LLM-summarised session intents](./adrs/0002-llm-summarized-session-intents.md) — why intent text is the input to clustering and how it is sourced today (`$mcp_intent` per event) versus the session-level summary table being built in parallel.
- [0003 — Persist intent clusters as a per-team snapshot](./adrs/0003-intent-clustering-snapshot.md) — why clustering writes a denormalised JSON snapshot per team (`MCPIntentClusterSnapshot`) rather than computing on read or modelling clusters relationally.

## Conventions

- Each PRD and ADR gets a zero-padded sequence number (`0001`, `0002`, ...). Never renumber after merge.
- ADRs follow a lightweight "Context / Decision / Consequences / Alternatives" structure. Status is one of `Proposed`, `Accepted`, `Superseded by NNNN`.
- PRDs are short. Use them to capture intent, scope boundaries, surfaces, and success metrics — not implementation detail. Implementation belongs in the code and in ADRs.
- When a decision changes, write a new ADR and mark the old one `Superseded by NNNN`. Do not rewrite history.
