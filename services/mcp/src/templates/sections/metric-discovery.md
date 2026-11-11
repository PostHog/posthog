#### Metric discovery (semantic layer)

Catalog-first is decided by request shape, not by whether the noun sounds like a KPI: a count, sum, or amount of X per day/hour/week/month/year, a rate or percentage of X, an average/percentile/latency of X, a cost per X, or a conversion between two events — plus their rankings, breakdowns, comparisons, synonyms, derived forms, and definition questions. X is anything the product records: sessions, 404s, tickets, tool calls, revenue. Label derivations noncanonical in `context`, and say plainly in the answer that the number is a one-off, not a saved definition. One-off exploration and debugging aggregates stay schema-first.

The first call for that shape is `metric-list`; `read-data-schema`, `info query-*`, and `search <noun>` are not substitutes. It outranks 'Retrieving data', typed domain tools, and any skill's query recipe. Read every page. `exec search` finds tools, not catalog rows.

- Match measure, dimensions, grain, and time. With materially different approved matches, ask once and END YOUR TURN. Until the reply, no more tool calls and no results.
- For an exact match, call `data-catalog-metric-run` instead of running its query yourself. If only time or interval differ on an insight-based metric, pass them to the run. Otherwise, if the measure fits, adapt its `metric-describe` query, run it with `execute-sql`, explain the change, and don't call it canonical.
- An approved match outranks a `proposed` or drifted one. Check response `status` and `is_drifted` before calling it canonical. Use a drifted/proposed one only if its definition fits, and follow the run's `NONCANONICAL` note. Either way, warn the user that it is proposed or drifted, and say why you used it or not.
- For a drill-down such as "which tools are driving the failures?", run the canonical metric for the headline first, then label the breakdown noncanonical.
- With no match, put "governed catalog consulted: no match" in the `context` argument of the `execute-sql` call that answers it, never in the answer; with no such call, omit it. Explain failures. Offer to save a reusable settled measure as a proposed metric, not a one-off aggregate.
- After an approved, non-drifted run, open with `🛡️ **From your data catalog**: <display_name>, approved definition, reviewed by <approver> on <date like Oct 6, 2026>`, both from `metric-describe`. No 🛡️ elsewhere.
- Listings: omit the filter and report status. Never edit metrics.
