# Chart delivery by client

- In PostHog AI, the successful typed-query response supplies the native chart. Give the findings without a separate render call.
- If the response says an interactive view is already visible, give the findings without a second chart.
- For an MCP app client that needs a render step, use the client's tool search to find the top-level `posthog:render-ui`. Search inside `posthog:exec` does not find this separate tool.
- Check that `render-ui` supports the successful query tool in its `tool_name` enum. Call it directly with that tool name and the exact successful input as `tool_input`. Preserve all dates, filters, and settings; do not pass result rows.
- Slack uses its integration's supported attachments or links. Do not assume that a native PostHog AI or MCP app chart is visible there.
- If no supported chart path exists, state the limit and give the findings. Do not create SQL, save an insight, or invent an unsaved-insight link to get a chart.
- A supporting table can accompany the chart. Use the successful query result for both, and honor explicit table requests.
