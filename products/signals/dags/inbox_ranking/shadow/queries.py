"""SQL for the shadow evaluation: the lists the inbox served, and what people did with them.

Both queries read the dogfood project's client telemetry, the same stream the label assets read,
and both are bounded by explicit event-time windows so a partition is reproducible for any past
day. The impression query is the ranking unit: one `Inbox reports impressed` event is one list a
person saw, in the order the list served it.
"""

import datetime
from typing import Any

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.signals.dags.inbox_ranking.dataset.queries import IMPRESSION_RANK_SQL, etl_workload, utc_bound

# The action types the `action` head counts as a positive (products/signals/dags/inbox_ranking/
# training/heads.py). Kept identical so both reads count the same event family. The head's seven-day
# horizon and its per-report grain are deliberately not carried over; `shadow/metrics.py` says why.
ACTION_TYPES = ("create_pr", "discuss")

_ACTION_TYPES_SQL = ", ".join(f"'{action_type}'" for action_type in ACTION_TYPES)

# One row per (impression event, report). `impression_id` is the event's own uuid, which makes the
# served list the grouping key: every report in one event was ranked against the others in it.
#
# The GROUP BY is a delivery guard, not an aggregate: analytics capture is at-least-once, so the
# same event can land twice and would then put a report into its own list twice. `rank` is read
# through the same 1-based contract guard the labels asset applies, and a report whose rank is
# missing or malformed cannot be placed in the served order at all, so it is dropped here.
IMPRESSION_COLUMNS = ("impression_id", "distinct_id", "impressed_at", "tab", "scope", "report_id", "served_rank")
IMPRESSION_LISTS_SQL = f"""
SELECT
    impression_id,
    any(distinct_id) AS distinct_id,
    min(timestamp) AS impressed_at,
    any(tab) AS tab,
    any(scope) AS scope,
    report_id,
    any(rank_value) AS served_rank
FROM (
    SELECT
        toString(uuid) AS impression_id,
        distinct_id,
        timestamp,
        toString(properties.tab) AS tab,
        toString(properties.scope) AS scope,
        JSONExtractString(imp, 'report_id') AS report_id,
        {IMPRESSION_RANK_SQL} AS rank_value
    FROM events
    ARRAY JOIN JSONExtractArrayRaw(properties, 'impressions') AS imp
    WHERE event = 'Inbox reports impressed'
      AND timestamp >= toDateTime({{window_start}}) AND timestamp < toDateTime({{window_end}})
)
GROUP BY impression_id, report_id
HAVING report_id != '' AND served_rank IS NOT NULL
"""

# One row per engagement, tagged with the head whose outcome it is. Attribution to a list happens
# in pandas: an engagement belongs to the impression of the same person and report that it follows
# inside the attribution window.
OUTCOME_COLUMNS = ("report_id", "distinct_id", "timestamp", "outcome")
OUTCOMES_SQL = f"""
SELECT
    toString(properties.report_id) AS report_id,
    distinct_id,
    timestamp,
    if(event = 'Inbox report opened', 'open', 'action') AS outcome
FROM events
WHERE (
        event = 'Inbox report opened'
        OR (event = 'Inbox report action' AND toString(properties.action_type) IN ({_ACTION_TYPES_SQL}))
    )
  AND timestamp >= toDateTime({{window_start}}) AND timestamp < toDateTime({{window_end}})
  AND toString(properties.report_id) != ''
"""


def hogql_rows(
    sql: str,
    *,
    team: Team,
    query_type: str,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> list[tuple[Any, ...]]:
    """Both queries scan one day of one event family, so they keep the HogQL default timeout
    rather than the cumulative label windows' 600s."""
    response = execute_hogql_query(
        query=sql,
        team=team,
        query_type=query_type,
        placeholders={
            "window_start": ast.Constant(value=utc_bound(window_start)),
            "window_end": ast.Constant(value=utc_bound(window_end)),
        },
        limit_context=LimitContext.SAVED_QUERY,
        workload=etl_workload(),
        settings=HogQLGlobalSettings(max_execution_time=600),
        # The dag runs without a user; the read is a trusted internal ETL over the dogfood project.
        bypass_warehouse_access_control=True,
    )
    return [tuple(row) for row in response.results or []]
