List the persons behind a paths insight — either everyone who traversed the path, or those at one specific node/edge.

Pair this with `query-paths`: first run the paths query to see the flows (each result row is an edge `source → target` with a user count), then call this tool with the **same** paths query as `source`.

Two modes:

**1. Everyone on the path (A → B).** Set `startPoint` / `endPoint` on the source `pathsFilter` and leave the path keys unset. Returns every actor whose journey matches that start/end constraint. Use this for "who went from a.com to b.com?".

**2. Actors at a specific point.** Each node in the path graph has a key of the form `<stepIndex>_<value>` (e.g. `"3_https://example.com/checkout"`). The `source` and `target` fields of a `query-paths` result row **are** these keys — copy them verbatim. Set on the source `pathsFilter`:

- `pathEndKey` — persons who **arrived at** that node (use a row's `target`).
- `pathStartKey` — persons who **departed from** that node (use a row's `source`).
- Set **both** `pathStartKey` + `pathEndKey` to pin a single edge (the actors behind one `source → target` count).
- `pathDropoffKey` — persons who **dropped off** at that node. Mutually exclusive with the other two.

Selectors:

- `includeRecordings`: defaults to `true`. Set to `false` to skip fetching matched session recordings (faster if recordings are not needed).

Response:

Each returned row contains `distinct_id`, `name`, `email`, and `event_count` (number of matching events for that actor). When `includeRecordings` is `true` (the default), a `recordings` column is also returned with PostHog replay URLs. Results are limited to the top 100 actors ordered by event count.

Guidance:

- Keep the `source` paths query minimal — only include the filters needed to define the same population the user is asking about.
- The path keys come straight from a `query-paths` result row's `source` / `target`; do not hand-construct them.
- `pathReplacements` and `showFullUrls` are not exposed — they don't change which actors are returned (`showFullUrls` is display-only; `pathReplacements` is covered by `localPathCleaningFilters`).
- For large result sets, narrow the source (start/end point, date range, filters) rather than expecting more rows.
