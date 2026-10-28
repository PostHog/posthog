# Render a typed query result

Run the typed query to get the data for the answer. Then use a chart path that the host supports.
Keep the same query definition for both steps so that the chart uses the same filters, dates, and calculation.

## Find the renderer

In PostHog AI, a successful typed query supplies its query node to a native chart widget.
This path does not need an interactive-view text note or a separate `render-ui` call.
Give the conclusion without another chart or a SQL chart link.

For an MCP app host, read the successful query response first. If it says the user already sees an interactive view, the chart is displayed.
Give the conclusion without a second chart or a SQL chart link.

If an MCP app host needs a separate render step, check its full tool catalog for `posthog:render-ui`.
Some hosts defer tool definitions until you search for them. Use the host's tool-search facility with `render-ui`.
The `search` command inside `posthog:exec` searches the query and entity tools. It does not discover this separate top-level tool.

Inspect the renderer's `tool_name` enum. Use it only when that enum includes the successful query tool.
Call the renderer directly through the host. Calling `render-ui` inside `posthog:exec` does not display its widget.

## Reuse the successful input

For example, after you verify that `$pageview` is the event you need, run `posthog:query-trends` with:

```json
{
  "series": [{ "kind": "EventsNode", "event": "$pageview", "math": "total" }],
  "dateRange": { "date_from": "-7d" },
  "interval": "day",
  "trendsFilter": { "display": "ActionsLineGraph" }
}
```

If this returns data without an inline chart and `query-trends` is in the renderer's enum, call `posthog:render-ui` with:

```json
{
  "tool_name": "query-trends",
  "tool_input": {
    "series": [{ "kind": "EventsNode", "event": "$pageview", "math": "total" }],
    "dateRange": { "date_from": "-7d" },
    "interval": "day",
    "trendsFilter": { "display": "ActionsLineGraph" }
  }
}
```

Use the complete input that succeeded in your query. Preserve any breakdown, property filters, comparison, and other query settings.
Do not substitute result rows, omit filters, or translate the query to SQL.
The same workflow applies to `posthog:query-funnel`, `posthog:query-retention`, and the other typed query tools in the enum.

## Finish the answer

Check that the inline response or render call succeeded. Then give a short conclusion with the values that support it.
Outside the native PostHog AI widget path, a data query alone does not confirm that a chart is displayed.
A link that opens an analysis does not confirm an inline chart either.

Slack uses its integration's attachment and link support. Do not treat an MCP app response as a displayed Slack chart.

If no supported chart path exists, state that limit and summarize the typed result.
Do not construct a SQL chart link or save an insight to work around the limit.
If the user asks to save an insight, save the typed query as its native query node.
