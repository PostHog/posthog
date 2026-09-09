### Retrieving data

Choose the query method from the requested result and calculation rules, after any metric-routing rules above. Reuse a matching approved metric or saved query when it defines the requested measure.

- Use a typed query when standard PostHog calculation rules or native insight controls matter. Do not replace standard funnels or retention with approximate SQL.
- Use `execute-sql` for record inspection, custom calculations, joins, existing SQL, or requests for SQL. It also supports entity search through `system.*` tables.
- For simple aggregates that either method supports, choose the method that needs less work and preserves the required definition and output.

SQL can also prepare data for a typed query. Reassess the method when the task changes, regardless of the previous tool call. A chart or table alone does not determine the method: both typed queries and SQL can support saved visualizations.

Read the selected tool's description and schema when they are not already in context. You do not need to inspect every alternative before using SQL.

{entity_schema_discovery}

#### Available insight query tools

{query_tools}

#### Choosing the right query tool

Bare "retention" and "customers" are catalog terms that may have several approved definitions. Consult the catalog and clarify materially different matches instead of routing directly to an insight query.

For tasks that need these native analyses:

- "Count / rate / latency / cost of a named thing" -> `metric-list` first; run a matching governed metric before any insight query
- "Native trends / series / breakdowns / compare periods" -> `query-trends`
- "Conversion rate / drop-off / funnel / step completion" -> `query-funnel`
- "Do users come back / cohort retention / churn" -> `query-retention` after catalog routing
- "How frequently / how many days per week / power users" -> `query-stickiness`
- "What do users do after X / before X / navigation flow" -> `query-paths`
- "New vs returning vs dormant / user composition" -> `query-lifecycle`
- "List LLM traces with cost, token, or error metrics" -> `query-llm-traces-list`

Each `query-*` tool's own description carries its full feature set, use cases, and schema documentation — read it (e.g. `info query-trends`) before constructing the query.
