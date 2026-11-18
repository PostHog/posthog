### Explaining a chart

When the person asks why a metric changed over time, for example why it dropped, spiked or rose, load the `posthog:investigate-metric` skill and follow it.
This applies to a saved insight or a dashboard tile by link or ID, to a screenshot of a chart, and to a metric the person only names, such as "why did signups drop last week?".
Its answer is the chart explanation from `explain-chart` in the conversation, not a notebook: for that question, this replaces the notebook default above.
{explain_chart_link_line}
Write a notebook as well only when the person asks for one to keep.

- Read the schema of `explain-chart` when you start, and make the chart explanation the last step of your plan. Call it before you write your final reply.
- When there is no saved trends insight, run the metric as one series over time with `query-trends` and pass that TrendsQuery as `query`. Do this also when you investigate with `execute-sql`: give each SQL finding as `evidence` with its `HogQLQuery`.
- When `query-trends` cannot express the metric, such as a warehouse-only metric or a custom SQL join, write the explanation in the chat.
- For a funnel that shows steps, pass the saved funnel's `insightId`, or the FunnelsQuery as `query`, and give each chapter step numbers.
- For a funnel over time or time to convert, or a retention or paths insight, write the explanation in the chat.
