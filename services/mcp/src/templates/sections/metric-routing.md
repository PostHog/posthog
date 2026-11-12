Bare "retention" and "customers" are catalog terms that may have several approved definitions. Consult the catalog and clarify materially different matches instead of routing directly to an insight query.

For tasks that need these native analyses:

- "Count / rate / latency / cost of a named thing" -> `metric-list` first; run a matching governed metric before any insight query
- "How many / how much / over time / compare periods" -> `metric-list` first, then `query-trends` if no metric fits, approved or proposed
- "Conversion rate / drop-off / funnel / step completion" -> `metric-list` first, then `query-funnel` if no metric fits, approved or proposed
- "Do users come back / cohort retention / churn" -> `query-retention` after catalog routing
- "How frequently / how many days per week / power users" -> `query-stickiness`
- "What do users do after X / before X / navigation flow" -> `query-paths`
- "New vs returning vs dormant / user composition" -> `query-lifecycle`
- "List LLM traces with cost, token, or error metrics" -> `query-llm-traces-list`
