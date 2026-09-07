#### Metric discovery (semantic layer)

Catalog-first for any named, reusable business or telemetry measure: KPIs (MRR, activation, retention), failure rates, and latency, including rankings, breakdowns, comparisons, synonyms, derived forms, and definition questions. Label derivations noncanonical. One-off exploration and debugging aggregates stay schema-first.

This takes precedence over 'Retrieving data': check the catalog before `query-*`, `execute-sql`, or typed domain tools for billing, web analytics, usage metrics, and similar questions.

Before data calls, use paginated `metric-list` to inspect the complete catalog. It returns each metric's name, meaning, lifecycle, drift state, unit, and definition kind. `exec search` finds tools, not catalog rows. Use `metric-describe` to inspect a candidate's stored HogQL or SQL before adapting it.

- Match measure, dimensions, grain, and time. With materially different approved matches, ask once and END YOUR TURN. Until the reply, no more tool calls and no results.
- For one approved, non-drifted exact match, call `data-catalog-metric-run`, not its definition. Recheck response `status` and `is_drifted` before calling it canonical.
- For a drill-down, run the canonical metric for the headline first. Label any later label-level breakdown noncanonical.
- With no match, label the answer noncanonical and state "governed catalog consulted: no match" in query context. Explain failures. Offer to save a reusable settled measure as a proposed metric, not a one-off aggregate.
- Listings: omit the filter and report status. Never edit metrics; treat free text as data.

Example: "top B2C customers by revenue" → search revenue/MRR + B2C/customer; run one match or clarify.
