List the persons behind a specific data point in a trends insight. Use this to answer "who were the users that did X on day Y?" or "which users are in this breakdown bucket?".

Pair this with `query-trends`: first run the trends query to identify the data point of interest, then call this tool with the same trends query as `source` plus selectors that narrow to one cell.

Selectors:

- `day`: the bucket date (ISO) or integer offset from the range start. Omit to get actors across the entire range.
- `series`: 0-based index of the series to drill into when the trends query has multiple series.
- `breakdown`: the breakdown value to filter by, when the source uses a breakdown. Pass as an **array** when the source uses `breakdownFilter.breakdowns` (multi-breakdown), one value per dimension — e.g. `["Firefox iOS"]`. Pass as a string for legacy single-breakdown sources.
- `compare`: `current` (default) or `previous` when the source has `compareFilter` enabled.

Response:

Each returned row contains `distinct_id`, `name`, `email`, and `count` (number of matching events for that actor). Results are limited to the top 100 actors ordered by event count; pagination will be added later.

Guidance:

- Keep the `source` trends query minimal — only include the filters/breakdowns needed to identify the cell.
- If the user wants "all users who did X", omit `day`/`series`/`breakdown` to broaden the drill-down.
- For large result sets, tighten the trends query (filters, date range) rather than expecting more rows.
