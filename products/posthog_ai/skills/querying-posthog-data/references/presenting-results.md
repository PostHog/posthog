# Present query results

## Choose the display

- Use charts for time series, category comparisons, funnels, and retention. Select a display that fits the question before running the query.
- A supporting table can accompany the chart when exact values help answer the question. Honor explicit table requests.
- Keep the successful typed query as the source of the chart, written values, and any supporting table.

## Deliver the chart

- **PostHog AI:** a successful typed-query response supplies its query node to the native chart widget. No separate render call or SQL chart link is needed.
- **Already displayed:** when the client or response confirms that the interactive view is visible, give the findings without a second chart.
- **MCP app host:** if a separate render step is needed, use the host's tool search to find the top-level `posthog:render-ui`. Search inside `posthog:exec` does not discover this separate tool.
- **Renderer available:** check that the query tool is in its `tool_name` enum. Call `posthog:render-ui` directly with that name and the exact successful query input as `tool_input`. Preserve dates, filters, and settings. Do not pass result rows. See the [worked example](./rendering-typed-query-results.md).
- **Slack:** follow the integration's supported attachments and links. An MCP app or PostHog AI widget does not establish that a chart is visible in Slack.
- **No supported chart path:** state the limit and summarize the typed result. Do not rewrite a supported typed query as SQL or invent an unsaved-insight link to get a chart.

## Explain the result

- Start with the main finding and the values that support it. For several metrics, explain the main change in each.
- State the date range, counting method, and any incomplete intervals that affect the comparison.
- Check that the conclusion and any supporting table agree with the query result.
- Tool calls through `exec` or a shell do not determine the user's display. Use the client's chart contract to decide whether rendering is complete.
- Save a new insight only when the user asks.
