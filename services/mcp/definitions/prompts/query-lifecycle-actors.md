List the persons in a specific bucket of a lifecycle insight. Use this to answer "who are the new / returning / resurrecting / dormant users on day Y?".

`source` is the lifecycle query that defines the population (event, date range, filters). Build it directly when the user's request already names a bucket-day, or reuse one you previously ran via `query-lifecycle` when drilling in from a chart.

Selectors:

- `day` **(required)**: the bucket date as an ISO date string (YYYY-MM-DD), e.g. `"2024-01-15"`. Must align with the source's interval (a day boundary for `interval=day`, the start of the week for `interval=week`, etc.).
- `status` **(required)**: which lifecycle bucket to drill into. One of `new`, `returning`, `resurrecting`, `dormant`.
  - `new` — users seen for the first time (person profile created) during the period.
  - `returning` — users active in the previous period and active in this one.
  - `resurrecting` — users inactive for one or more periods and active again now.
  - `dormant` — users active in the previous period but inactive now.
- `limit`: how many persons to return in one page. Defaults to 100, and anything above 1000 is clamped to 1000.
- `offset`: how many persons to skip before the returned page. Defaults to 0.

Response:

Each returned row contains `distinct_id`, `email`, and `name`. Matched session recordings are not returned — the lifecycle runner does not project per-actor matching events.

The response also reports `limit`, `offset`, and `hasMore`. When `hasMore` is `true` there are more people in the bucket — call again with `offset` raised by `limit` to read the next page, and repeat until `hasMore` is `false`.

Guidance:

- Lifecycle excludes anonymous users (events with `$process_person_profile: false`), so actor lists only contain identified users — anonymous visitors never appear in any bucket.
- Lifecycle insights only support a single series and do not expose `compareFilter`, so there is no `series` or `compare` selector here.
- Keep the `source` lifecycle query minimal — only include the filters needed to define the same lifecycle population the user is asking about.
- To read every person in a bucket, page with `offset` rather than raising `limit` past 1000, and keep `source`, `day`, and `status` identical across pages so rows don't repeat or go missing.
- When you only need a sample, one page is enough — tighten the source query (filters, date range) instead of paging through everyone.
