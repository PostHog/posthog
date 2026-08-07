**CORRECT usage pattern:**

<example>
User: create pageviews visualization
Assistant: This needs analytics and visualization guidance, so I'll load both first.
[Runs `posthog:exec({"command":"learn analytics visualizations"})`]
</example>

<example>
User: How many weekly active users do we have?
Assistant: This needs analytics and visualization guidance, so I'll load both before any other command.
[Runs `posthog:exec({"command":"learn analytics visualizations"})`]
Assistant: I need the query and data schema tools.
[Runs `posthog:exec({"command":"search query-trends"})` and `posthog:exec({"command":"search read-data"})` in parallel]
Assistant: I'll inspect both schemas.
[Runs `posthog:exec({"command":"info query-trends"})` and `posthog:exec({"command":"info read-data-schema"})` in parallel]
Assistant: The hinted series needs its full schema, and I need the team's events.
[Runs `posthog:exec({"command":"schema query-trends series"})` and `posthog:exec({"command":"call read-data-schema {\"query\":{\"kind\":\"events\"}}"})` in parallel]
Assistant: I now have the inputs for the query.
[Runs `posthog:exec({"command":"call query-trends {...}"})`]
Assistant: [Briefly summarizes the weekly active user trend.] I'll render it so you can verify the result.
[Runs `render-ui({ "tool_name": "query-trends", "tool_input": {...} })` with the same query input]
</example>

<example>
User: Create a dashboard for our key revenue metrics
Assistant: Analytics applies. I'll load it before any other command.
[Runs `posthog:exec({"command":"learn analytics"})`]
Assistant: I need dashboard and query tools.
[Runs `posthog:exec({"command":"search dashboard"})` and `posthog:exec({"command":"search execute-sql"})` in parallel]
Assistant: I'll inspect both schemas.
[Runs `posthog:exec({"command":"info dashboard-create"})` and `posthog:exec({"command":"info execute-sql"})` in parallel]
Assistant: I have the inputs to create the dashboard.
[Makes call commands with correct parameters]
</example>

**INCORRECT usage patterns: NEVER do this**

<bad-example>
User: Show me our feature flags
Assistant: [Calls `feature-flag-get-all` with guessed parameters]
WRONG: Run `info feature-flag-get-all` first.
</bad-example>

<bad-example>
User: Query our events
Assistant: [Loads analytics, then calls three tools without inspecting them]
WRONG: Run `info` for all tools before any `call` commands.
</bad-example>

<bad-example>
User: Show me a trends chart of signups
Assistant: [Runs `learn analytics visualizations`, then runs `info query-trends` and guesses the hinted series structure]
WRONG: Run `schema query-trends series` before populating a field with a drill-down hint.
</bad-example>

<bad-example>
User: query pageviews for the last 7 days
Assistant: [Runs `learn analytics`, then queries the guessed `$pageview` event]
WRONG: Confirm the event with `call read-data-schema {"query":{"kind":"events"}}` first.
</bad-example>
