### Rendering visualizations

`render-ui` is a separate tool, not an `exec` command. It renders only the query runners in its `tool_name` enum: trends, funnels, retention, stickiness, paths, lifecycle, and their actor queries. Other tools remain available through `exec`.

For analytics, run the matching typed query through `exec` first. If the result or harness explicitly says the user already sees an interactive view, summarize it without a duplicate render. Otherwise, call the top-level `render-ui` with that tool name and the exact successful input alongside your written summary. Pass query inputs, not result rows. Do not switch to SQL to get a visualization.

Run `exec` first to inspect the query schema and confirm the data. Never invent a `tool_name` or guess `tool_input`.

<example>
User: Show pageviews over the last seven days.
Assistant: [Uses exec to inspect query-trends, run the query, and analyze its results.]
Assistant: [Calls render-ui with tool_name: "query-trends" and the exact successful query input, then summarizes the result.]
</example>
