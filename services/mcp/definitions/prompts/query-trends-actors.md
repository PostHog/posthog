List the persons behind a specific data point in a trends insight. Use this to answer "who were the users that did X on day Y?" or "which users are in this breakdown bucket?".

Pair this with `query-trends`: first run the trends query to identify the data point of interest, then call this tool with the same trends query as `source` plus selectors that narrow to one cell.

Selectors:

- `day` **(required)**: a single bucket date as an ISO date string (YYYY-MM-DD), e.g. `"2024-01-15"`. Must match exactly one data point from the trends result.
- `series`: 0-based index of the series to drill into when the trends query has multiple series. Defaults to 0.
- `breakdown`: always an array, one value per `breakdownFilter.breakdowns` dimension, in the same order. Single dimension: `breakdown: ["Opera"]`. Multiple dimensions: `breakdown: ["Opera", "en-US"]`.
- `compare`: `current` (default) or `previous` when the source has `compareFilter` enabled.
- `includeRecordings`: defaults to `true`. Set to `false` to skip fetching matched session recordings (faster if recordings are not needed).

Response:

Each returned row contains `distinct_id`, `name`, `email`, and `event_count` (number of matching events for that actor). When `includeRecordings` is `true` (the default), a `recordings` column is also returned containing PostHog replay URLs that can be opened in a browser to watch the user's session. Results are limited to the top 100 actors ordered by event count.

Guidance:

- Keep the `source` trends query minimal - only include the filters/breakdowns needed to identify the cell.
- Always pick a specific `day` from the trends result.
- For large result sets, tighten the trends query (filters, date range) rather than expecting more rows.
