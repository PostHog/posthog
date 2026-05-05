### Retrieving data

**Always use `query-*` tools when the question maps to a supported insight type.** These tools produce typed, saveable insights that map cleanly to the visual product; raw SQL forfeits that and is harder to iterate on. Before reaching for `execute-sql` for an analytics question, ask: "Can this be expressed as a `query-trends` series, breakdown, formula, property filter, or math operation?" If yes, the `query-*` tool is mandatory — see `Choosing the right query tool` below for prompt-to-field patterns.

Reach for `execute-sql` only when no `query-*` tool can express the question:

- Searching PostHog entities (insights, dashboards, cohorts, flags…) via `system.*` tables — no `query-*` tool covers entity search.
- Multi-event joins, custom CTEs, window functions, or data-warehouse joins.
- Pre-filtering or shaping data before running a `query-*` call.

When you do use `execute-sql`, run `info execute-sql` first to load its full guidance.

#### Searching for existing entities

Any "find / which / do we have / what's our X chart" question about PostHog-created entities is a SQL search against `system.*`, **not** a `*-list` walk. The list tools paginate over the entire team; SQL with ILIKE/FTS returns the matches in one call.

Map intent to table:

- "find an insight" / "what's our X chart" / "is this insight saved" → `system.insights`
- "find a dashboard" → `system.dashboards`
- "find a cohort" → `system.cohorts`
- "find a feature flag" → `system.feature_flags`
- "find an experiment" → `system.experiments`
- "find a survey" → `system.surveys`
- "find a notebook" → `system.notebooks`

Search rules:

1. **One query, multiple columns.** Combine `name ILIKE '%term%' OR description ILIKE '%term%'` rather than running separate queries.
2. **Filter `NOT deleted`** — every `system.*` table has soft-deletes.
3. **Order by recency** (`last_modified_at DESC` or `created_at DESC`) and `LIMIT 20-50` so the most relevant rows surface first.
4. **Verify the match with the entity's retrieve tool, not another SELECT.** Once SQL narrows to one or a few candidates, call the per-entity retrieve tool with the candidate's ID — for example `insight-get`, `dashboard-get`, `experiment-get`, `survey-get`, or `cohorts-retrieve` / `error-tracking-issues-retrieve`. Naming is inconsistent across entities; if the bare `<entity>-get` doesn't exist, run `search <entity>` and pick the read-shaped tool. **Do not run a second `execute-sql` to fetch the full row by ID.** The retrieve tool returns the authoritative entity shape (dashboards, query, ownership, last-viewed, etc.) in one call; re-querying via SQL costs an extra round-trip and only sees the columns exposed on the `system.*` table.
5. **Fallback to list tools.** If the entity has no `system.*` table (e.g. workflows, error-tracking issues, log views), or if SQL returns nothing after broadening the ILIKE pattern, fall back to the entity's `*-list` tool. SQL is the fast path; list tools are the floor.

<example>
User: Do we have any insights tracking revenue?
Assistant: [Runs `posthog:exec({ "command": "call execute-sql {\"query\":\"SELECT id, short_id, name, description, last_modified_at FROM system.insights WHERE NOT deleted AND (name ILIKE '%revenue%' OR description ILIKE '%revenue%') ORDER BY last_modified_at DESC LIMIT 20\"}" })`]
[Picks the most plausible match by name, then runs `posthog:exec({ "command": "call insight-get {\"id\": <id>}" })` (or pass the `short_id`) to verify the query, dashboards it's on, and last-viewed timestamp before reporting back to the user.]
<reasoning>SQL surfaces candidates fast; `insight-get` confirms the authoritative shape in one call — re-running `execute-sql ... WHERE id = <id>` would skip the dedicated tool and miss dashboards/ownership joins.</reasoning>
</example>

<bad-example>
User: Find me a graph of MAUs.
Assistant: [Runs `call execute-sql {"query":"SELECT * FROM system.insights WHERE id = 33800 LIMIT 1"}` after a search SELECT already surfaced id 33800]
WRONG — verify with `call insight-get {"id": 33800}` instead. Re-querying `system.insights` by ID is a SELECT that doesn't surface dashboard membership, last-viewed, or other relational data the retrieve tool joins for you.
</bad-example>

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

##### Trends

A trends insight visualizes events over time using time series. They're useful for finding patterns in historical data.

The trends insights have the following features:

- The insight can show multiple trends in one request.
- Custom formulas can calculate derived metrics, like `A/B*100` to calculate a ratio.
- Filter and break down data using multiple properties.
- Compare with the current period with previous.
- Apply various aggregation types, like sum, average, etc., and chart types.
- And more.

Examples of use cases include:

- How the product's most important metrics change over time.
- Long-term patterns, or cycles in product's usage.
- The usage of different features side-by-side.
- How the properties of events vary using aggregation (sum, average, etc).
- Users can also visualize the same data points in a variety of ways.

##### Funnel

A funnel insight visualizes a sequence of events that users go through in a product. They use percentages as the primary aggregation type. Funnels REQUIRE AT LEAST TWO series (events or actions), so the conversation history should mention at least two events.

The funnel insights have the following features:

- Various visualization types (steps, time-to-convert, historical trends).
- Filter data and apply exclusion steps (events only, not actions).
- Break down data using a single property.
- Specify conversion windows (default 14 days), step order (strict/ordered/unordered), and attribution settings.
- Aggregate by users, sessions, or specific group types.
- Sample data.
- Track first-time conversions with special math aggregations.
- And more.

Examples of use cases include:

- Conversion rates between steps.
- Drop off steps (which step loses most users).
- Steps with the highest friction and time to convert.
- If product changes are improving their funnel over time.
- Average/median/histogram of time to convert.
- Conversion trends over time (using trends visualization type).
- First-time user conversions (using `first_time_for_user` math).

##### Retention

A retention insight visualizes how many users return to the product after performing some action. They're useful for understanding user engagement and retention.

The retention insights have the following features: filter data, sample data, and more.

Examples of use cases include:

- How many users come back and perform an action after their first visit.
- How many users come back to perform action X after performing action Y.
- How often users return to use a specific feature.

#### SQL fallback

Reach for `execute-sql` only when the question genuinely cannot be expressed as a typed insight (entity search via `system.*`, multi-event joins, custom CTEs, data-warehouse joins). If the answer is a number over time, a comparison, a ratio, an aggregate, a step sequence, or a return-rate, use the matching `query-*` tool.
