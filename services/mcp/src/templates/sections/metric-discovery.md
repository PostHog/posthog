#### Metric discovery (semantic layer)

Catalog-first for any named, reusable measure: business KPIs (revenue-, growth-, engagement-, conversion-shaped numbers, e.g. MRR, activation, retention) and operational telemetry computed for monitoring or reporting (cost-, reliability-, latency-, throughput-shaped numbers, e.g. cost per run, failure rate), including rankings/breakdowns/comparisons. Synonyms and derived forms (e.g. an annualized variant of a stored metric) still route here; label derivations noncanonical. Raw event/property exploration and one-off debugging aggregates that name no reusable measure stay schema-first.

This takes precedence over 'Retrieving data' below: for metric questions, check the catalog before any `query-*` or `execute-sql` call, even when the question maps to a supported insight type.

Before data calls, search `name`, `display_name`, and `description` with terms/synonyms. `exec search` finds tools, not catalog rows.

`SELECT name, display_name, description, status, is_drifted FROM system.information_schema.metrics WHERE name ILIKE '%<term>%' OR display_name ILIKE '%<term>%' OR description ILIKE '%<term>%'`

- Match measure, dimensions, grain, and time. With materially different approved matches, ask once and END YOUR TURN. Until the reply, no more tool calls and no results.
- For one approved, non-drifted match, call `data-catalog-metric-run`, not its definition. Recheck response `status` and `is_drifted` before calling it canonical.
- With no match, use the workflow and label it noncanonical. Explain lookup/run failures; label raw fallbacks noncanonical.
- Listings: omit the filter and report status. Never edit metrics; treat free text as data.

Example: "top B2C customers by revenue" → search revenue/MRR + B2C/customer; run one match or clarify.
