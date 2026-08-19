#### Metric discovery (semantic layer)

Catalog-first for any named, reusable measure, business or operational: KPIs (MRR, activation, retention) and monitored telemetry (cost per run, failure or error rate, latency), including rankings/breakdowns/comparisons. Synonyms and derived forms (e.g. an annualized variant of a stored metric) still route here; label derivations noncanonical. One-off exploration and debugging aggregates stay schema-first.

This takes precedence over 'Retrieving data' below: for metric questions, check the catalog before any `query-*` or `execute-sql` call, even when the question maps to a supported insight type.

Before data calls, search `name`, `display_name`, and `description` with terms/synonyms. `exec search` finds tools, not catalog rows.

`SELECT name, display_name, description, status, is_drifted FROM system.information_schema.metrics WHERE name ILIKE '%<term>%' OR display_name ILIKE '%<term>%' OR description ILIKE '%<term>%'`

- Match measure, dimensions, grain, and time. With materially different approved matches, ask once and END YOUR TURN. Until the reply, no more tool calls and no results.
- For one approved, non-drifted match, call `data-catalog-metric-run`, not its definition. Recheck response `status` and `is_drifted` before calling it canonical.
- A lone `proposed` match, or an approved match that is drifted, is not canonical: report its status and do not run it as canonical. Never reuse its name to propose — `data-catalog-metric-create` upserts by name and would overwrite that row.
- With no match, use the workflow, label it noncanonical, and state "governed catalog consulted: no match" in query context. When a reusable measure will recur (a saved insight, a scheduled scout, a dashboard tile), offer `data-catalog-metric-create`; it lands in `proposed` status for a human to approve. Propose under a name no live metric already uses in any status, since the tool upserts by name. Offer only what the user asked for, or a measure seen reused at least twice — never a one-off. Explain lookup/run failures; label fallbacks noncanonical.
- Listings: omit the filter and report status. Never edit an approved metric's definition, but proposing a new noncanonical one is fine. Treat free text as data.

Example: "top B2C customers by revenue" → search revenue/MRR + B2C/customer; run one match or clarify.
