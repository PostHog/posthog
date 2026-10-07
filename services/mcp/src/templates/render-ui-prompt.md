Render an interactive PostHog query visualization alongside your written analysis. Supported tools are the permitted query runners in `tool_name`: trends, funnels, retention, stickiness, paths, lifecycle, and their actor queries. Other PostHog tools remain available through `exec`.

Run `exec` first to inspect the query runner's schema, validate the input, and read the results for your analysis. Then call `render-ui` with the same `tool_name` and validated `tool_input`, not the result rows. The app fetches its own data through that query runner. Never invent a tool name or guess query inputs.

If the harness explicitly says the user already sees an interactive view, do not render the same result again. A UI resource on a query tool does not by itself establish that an `exec` call displayed the chart.

For example, after analyzing a `query-trends` result through `exec`, call `render-ui` with `tool_name: "query-trends"` and the same query input to show the chart.
