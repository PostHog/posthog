### Retrieving data

**Always use the typed `client.query.*` methods when the question maps to a supported insight type.** They produce typed, saveable insights that map cleanly to the visual product; raw SQL forfeits that and is harder to iterate on. Before reaching for `sql` for an analytics question, ask: "Can this be expressed as a `query.trends` series, breakdown, formula, property filter, or math operation?" If yes, the query method is mandatory — see `Choosing the right query method` below for prompt-to-field patterns.

Reach for `sql` only when no `query.*` method can express the question:

- Searching PostHog entities (insights, dashboards, cohorts, flags…) via `system.*` tables — no query method covers entity search.
- Multi-event joins, custom CTEs, window functions, or data-warehouse joins.
- Pre-filtering or shaping data before running a `query.*` call.

{entity_schema_discovery}

#### Available insight query tools

{query_tools}

Each `query-<name>` tool above is the SDK method `client.query.<name camel-cased>` (`query-trends` → `query.trends`, `query-llm-traces-list` → `query.llmTracesList`). Fetch its exact params with `types` before constructing the query.

#### Choosing the right query method

By insight type:

- "How many / how much / over time / compare periods" -> `query.trends`
- "Conversion rate / drop-off / funnel / step completion" -> `query.funnel`
- "Do users come back / retention / churn" -> `query.retention`
- "How frequently / how many days per week / power users" -> `query.stickiness`
- "What do users do after X / before X / navigation flow" -> `query.paths`
- "New vs returning vs dormant / user composition" -> `query.lifecycle`
- "LLM traces / AI generations / token usage" -> `query.llmTracesList`
