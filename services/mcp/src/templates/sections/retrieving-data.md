### Retrieving data

**Always use `query-*` tools when the question maps to a supported insight type.** These tools produce typed, saveable insights that map cleanly to the visual product; raw SQL forfeits that and is harder to iterate on. Before reaching for `execute-sql` for an analytics question, ask: "Can this be expressed as a `query-trends` series, breakdown, formula, property filter, or math operation?" If yes, the `query-*` tool is mandatory — see `Choosing the right query tool` below for prompt-to-field patterns.

Reach for `execute-sql` only when no `query-*` tool can express the question:

- Searching PostHog entities (insights, dashboards, cohorts, flags…) via `system.*` tables — no `query-*` tool covers entity search.
- Multi-event joins, custom CTEs, window functions, or data-warehouse joins.
- Pre-filtering or shaping data before running a `query-*` call.

When you do use `execute-sql`, run `info execute-sql` first for the full discovery workflow, worked examples, and column-handling rules — this section only summarizes routing.

{entity_schema_discovery}

#### Available insight query tools

{query_tools}

#### Choosing the right query tool

By insight type:

- "How many / how much / over time / compare periods" -> `query-trends`
- "Conversion rate / drop-off / funnel / step completion" -> `query-funnel`
- "Do users come back / retention / churn" -> `query-retention`
- "How frequently / how many days per week / power users" -> `query-stickiness`
- "What do users do after X / before X / navigation flow" -> `query-paths`
- "New vs returning vs dormant / user composition" -> `query-lifecycle`
- "LLM traces / AI generations / token usage" -> `query-llm-traces-list`

Each `query-*` tool's own description carries its full feature set, use cases, and schema documentation — read it (e.g. `info query-trends`) before constructing the query.
