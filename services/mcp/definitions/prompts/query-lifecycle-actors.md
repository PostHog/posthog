List the persons in a specific bucket of a lifecycle insight. Use this to answer "who are the new / returning / resurrecting / dormant users on day Y?".

`source` is the lifecycle query that defines the population (event, date range, filters). Build it directly when the user's request already names a bucket-day, or reuse one you previously ran via `query-lifecycle` when drilling in from a chart.

Selectors:

- `day` **(required)**: the bucket date as an ISO date string (YYYY-MM-DD), e.g. `"2024-01-15"`. Must align with the source's interval (a day boundary for `interval=day`, the start of the week for `interval=week`, etc.).
- `status` **(required)**: which lifecycle bucket to drill into. One of `new`, `returning`, `resurrecting`, `dormant`.
  - `new` — users performing the event for the first time during the period.
  - `returning` — users active in the previous period and active in this one.
  - `resurrecting` — users inactive for one or more periods and active again now.
  - `dormant` — users active in the previous period but inactive now.
- `includeRecordings`: defaults to `true`. Set to `false` to skip fetching matched session recordings.

Response:

Each returned row contains `distinct_id`, `email`, and `name`. When `includeRecordings` is `true`, a `recordings` column is also returned with PostHog replay URLs. Results are limited to the top 100 actors.

Guidance:

- Lifecycle insights only support a single series and do not expose `compareFilter`, so there is no `series` or `compare` selector here.
- Keep the `source` lifecycle query minimal — only include the filters needed to define the same lifecycle population the user is asking about.
- For large buckets, tighten the source query (filters, date range) rather than expecting more rows.
