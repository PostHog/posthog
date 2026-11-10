# Conversion recordings

Behind `marketing-analytics-conversion-recordings`, positive event and action conversion cells open the existing Replay playlist in Ad performance and the legacy dashboard.
Ad and ad group rows, warehouse goals, and shared dashboards do not expose the action.

## Session selection

The product endpoint reuses the table's attribution query and campaign mappings to resolve the selected row.
It preserves the current period, filters, and conversion goal, and returns the session of the conversion event, not the attributed touchpoint.
Hidden grouping columns remain available as row keys without changing the saved column selection.
A missing campaign ID selects only the table's missing-ID row; comparison rows combine campaign IDs as the table does.
Multiple conversions in one session produce one session ID.
Pagination uses the last session ID as a cursor.
The modal sends at most 100 session IDs to Replay at a time; Previous and Next select the conversion session page.

## Availability and errors

Missing attribution precomputes return a preparing state with a retry action.
Failed requests show a query ID for tracing the request in ClickHouse query logs; each attempt uses a new ID.
Replay receives the selected session IDs and handles recording availability, permissions, and playback.
Conversions without session IDs have no replay, and a session may have no recording because it was not recorded or has expired.
The playlist does not apply an additional start-date or minimum-duration filter, because a conversion session can start before the selected conversion period.
Replay retains its native controls, including **Show all**, which can clear the session filter.
There is no intermediate people list, and the shared Replay components, query registry, and query cache are unchanged.
