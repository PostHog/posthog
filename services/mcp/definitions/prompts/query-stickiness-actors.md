List the persons behind one bar of a stickiness insight — the users who were active in a given number of intervals.

Pair this with `query-stickiness`: first run the stickiness query to read the distribution (the X-axis is the number of active intervals, the Y-axis is the number of users), then call this tool with the **same** stickiness query as `source` and `day` set to the bar you want to drill into.

Selectors:

- `day` **(required)**: the number of active intervals to drill into — the X-axis value of the bar. Despite the name, this is an interval **count**, not a date. For a daily insight, `day: 13` lists the users who were active on exactly 13 days within the source's date range; for a weekly insight it is a count of weeks, and so on.
- `series`: 0-based index of the series to drill into when the stickiness query has multiple series. Defaults to 0.
- `compare`: `current` (default) or `previous` when the source has `compareFilter` enabled.

Response:

Each returned row contains `distinct_id`, `email`, and `name`. Results are limited to the top 100 actors. There is no `event_count`, and there is no `includeRecordings` selector — stickiness drilldown is membership-based (active on exactly N intervals) and does not surface a matched-recordings column.

Guidance:

- Keep the `source` stickiness query identical to the one whose bar the user is asking about — the series, interval granularity, date range, and filters all determine who falls in each bar.
- `day` selects a single bar (a specific active-interval count), not a date. To list the users at a different bar, change `day`.
- For large result sets, tighten the source (date range, filters) rather than expecting more than 100 rows.
