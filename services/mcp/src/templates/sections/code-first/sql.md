### SQL (`sql`)

`sql <hogql>` runs a HogQL query and returns the same optimized output as the `execute-sql` tool. Everything after `sql` is the query — it may span multiple lines, with no quoting or escaping. Prefer it over embedding HogQL inside a `run` script; when a script genuinely needs SQL mid-flow, use `client.query.run({ query: { kind: 'HogQLQuery', query: '…' } })`.

Before writing any query, read the PostHog skill `querying-posthog-data` if it is available — HogQL differs from ClickHouse SQL, and the skill carries system-table schemas and worked examples.
