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
