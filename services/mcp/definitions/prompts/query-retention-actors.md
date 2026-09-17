List the persons in one retention acquisition cohort and show, for each, which subsequent intervals they came back in.

Pair this with `query-retention`: first run the retention query to see the cohort table (rows are acquisition cohorts, columns are intervals after acquisition), then call this tool with the **same** retention query as `source` to drill into one cohort.

Selectors:

- `interval`: which acquisition cohort to list, 0-based. `0` is the acquisition interval itself (every actor who entered the cohort), `1` is the cohort that entered one interval later, and so on. Defaults to `0`. This selects a **row** of the retention table; the returned columns then cover every interval for that cohort.
- `limit`: how many persons to return in one page. Defaults to 100, and anything above 1000 is clamped to 1000.
- `offset`: how many persons to skip before the returned page. Defaults to 0.

Response:

`results` is the per-person grid. Each row contains `distinct_id`, `email`, `name`, followed by one column per retention interval — `<period>_0` … `<period>_N`, where `<period>` is the retention period (`day` / `week` / `month` / `hour`). Each interval column is `1` if the actor was active in that interval and `0` if not. `<period>_0` is the acquisition interval and is always `1`. Rows are ordered by how many intervals the actor returned in (most-retained first).

The response also reports `limit`, `offset`, and `hasMore`. When `hasMore` is `true` there are more people in the cohort — call again with `offset` raised by `limit` to read the next page, and repeat until `hasMore` is `false`.

For the per-interval retention **counts and percentages** (the `Day N — count (pct%)` curve), run `query-retention` on the same `source` — those are computed over the whole cohort in one pass. Don't sum these (paged) rows to get cohort retention numbers.

The number and names of the interval columns come from the source: `retentionFilter.period` sets the prefix, and `retentionFilter.totalIntervals` (or `retentionCustomBrackets.length + 1` when custom brackets are set) sets how many columns there are.

There is no `includeRecordings` selector — retention's persons output is appearance-based and does not surface matched session recordings.

Guidance:

- Keep the `source` retention query identical to the one whose cohort the user is asking about — the cohort definition (target/returning events, period, type, brackets) determines who is in each cohort.
- `interval` picks the cohort (a **row** of the retention table), not a single cell. The response always spans every return interval as `<period>_N` columns. To get who returned in a specific interval, filter the rows where that column is `1` — the query returns the cohort's whole trajectory, not a single cell.
- To walk a whole cohort, page with `offset` rather than raising `limit` past 1000 — a page of 1000 people is already large, and paging keeps each response readable.
- Keep `source`, `interval`, and `limit` identical across the pages of one walk. Changing any of them re-cuts the cohort, so rows can repeat or go missing.
- When you only need a sample of the cohort, one page is enough — tighten the source (date range, filters) instead of paging through everyone.
