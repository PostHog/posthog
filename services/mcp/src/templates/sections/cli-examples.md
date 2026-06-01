**CORRECT usage pattern:**

<example>
User: How many weekly active users do we have?
Assistant: I need to find the right query tool and data schema tool.
[Runs posthog:exec({ "command": "search query-trends" }) and posthog:exec({ "command": "search read-data" }) in parallel]
Assistant: Let me check the tool descriptions and schemas.
[Runs posthog:exec({ "command": "info query-trends" }) and posthog:exec({ "command": "info read-data-schema" }) in parallel]
Assistant: I see query-trends needs `series` (array with hint). Let me get the full field schema and discover events.
[Runs posthog:exec({ "command": "schema query-trends series" }) and posthog:exec({ "command": "call read-data-schema {\"query\": {\"kind\": \"events\"}}" }) in parallel]
Assistant: Now I know the exact series structure and available events. Let me construct the query.
[Runs posthog:exec({ "command": "call query-trends {...}" })]
</example>

<example>
User: Create a dashboard for our key revenue metrics
Assistant: I'll need dashboard and query tools. Let me search for them.
[Runs posthog:exec({ "command": "search dashboard" }) and posthog:exec({ "command": "search execute-sql" }) in parallel]
Assistant: Let me check the schemas for the tools I'll need.
[Runs posthog:exec({ "command": "info dashboard-create" }) and posthog:exec({ "command": "info execute-sql" }) in parallel]
Assistant: Now I have both schemas. Let me start by searching for existing revenue insights.
[Makes call commands with correct parameters]
</example>

<example>
User: Find events related to onboarding
Assistant: Let me find the data schema tool.
[Runs posthog:exec({ "command": "search read-data" })]
[Runs posthog:exec({ "command": "info read-data-schema" })]
Assistant: Now I can list events and pick the onboarding-related ones.
[Runs posthog:exec({ "command": "call read-data-schema {\"query\": {\"kind\": \"events\"}}" })]
</example>

**INCORRECT usage patterns — NEVER do this:**

<bad-example>
User: Show me our feature flags
Assistant: [Directly calls posthog:exec({ "command": "call feature-flag-get-all {}" }) with guessed parameters]
WRONG — You must run `info feature-flag-get-all` FIRST to check the schema
</bad-example>

<bad-example>
User: Query our events
Assistant: [Calls three tools in parallel without any `info` calls first]
WRONG — You must run `info` for ALL tools before making ANY `call` commands
</bad-example>

<bad-example>
User: Show me a trends chart of signups
Assistant: [Runs info query-trends, sees summary with hints, then immediately calls query-trends with guessed series structure]
WRONG — info returned a summary with hint: "Run `schema query-trends series` for full structure".
You MUST follow the hint and run `schema` before constructing the series field.
</bad-example>

<bad-example>
User: query pageviews for the last 7 days
Assistant: [Runs `info query-trends`, then `call query-trends` with `event: "$pageview"` from the prompt]
WRONG — skipped `call read-data-schema {"query": {"kind": "events"}}`. Canonical-looking events still need confirmation per team.
</bad-example>

<bad-example>
User: show me the file downloads trend for the last 7 days
Assistant: [Runs `info query-trends`, then `call query-trends` with `event: "downloaded_file"` inferred from the wording]
WRONG — the real event might be `file_downloaded`, `download_completed`, or not captured. Confirm with `read-data-schema` before querying.
</bad-example>
