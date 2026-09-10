List the persons behind a specific data point in a trends insight. Use this to answer "who were the users that did X on day Y?" or "which users are in this breakdown bucket?".

Pair this with `query-trends`: first run the trends query to identify the data point of interest, then call this tool with the same trends query as `source` plus selectors that narrow to one cell.

Selectors:

- `day` **(required)**: a single bucket date as an ISO date string (YYYY-MM-DD), e.g. `"2024-01-15"`. Must match exactly one data point from the trends result.
- `series`: 0-based index of the series to drill into when the trends query has multiple series. Defaults to 0.
- `breakdown`: always an array, one value per `breakdownFilter.breakdowns` dimension, in the same order. Single dimension: `breakdown: ["Opera"]`. Multiple dimensions: `breakdown: ["Opera", "en-US"]`.
- `compare`: `current` (default) or `previous` when the source has `compareFilter` enabled.
- `includeRecordings`: defaults to `true`. Set to `false` to skip fetching matched session recordings (faster if recordings are not needed).
- `limit`: how many persons to return in one page. Defaults to 100, and anything above 1000 is clamped to 1000.
- `offset`: how many persons to skip before the returned page. Defaults to 0.

Response:

Each returned row contains `distinct_id`, `name`, `email`, and `event_count` (number of matching events for that actor), ordered by event count. When `includeRecordings` is `true` (the default), a `recordings` column is also returned containing PostHog replay URLs that can be opened in a browser to watch the user's session.

The response also reports `limit`, `offset`, and `hasMore`. When `hasMore` is `true` there are more people behind the data point — call again with `offset` raised by `limit` to read the next page, and repeat until `hasMore` is `false`.

Guidance:

- Keep the `source` trends query minimal - only include the filters/breakdowns needed to identify the cell.
- Always pick a specific `day` from the trends result.
- To read every person, page with `offset` rather than raising `limit` past 1000, and keep `source` and the other selectors identical across pages so rows don't repeat or go missing.
- When you only need a sample, one page is enough — tighten the trends query (filters, date range) instead of paging through everyone.
