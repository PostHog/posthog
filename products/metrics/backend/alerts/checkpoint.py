"""How far metrics ingestion has reached for a team, so an alert never reads a window still being written.

A series the pipeline has not written yet is absent from an instant query, and an absent series
resolves its group. So a consumer lag would read as recovery. The newest point the team's services
sent shows how far ingestion has reached: a lag delays every service at once.
"""

import datetime as dt
from typing import Final
from zoneinfo import ZoneInfo

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team

# Reads the `service_freshness_by_hour` projection of `metrics4_samples`, so it scans one row per
# service-hour. A point time is set by the sender, so a service whose clock runs ahead is left out.
_TEAM_FRESHNESS_QUERY: Final = parse_select(
    """
    SELECT maxOrNull(service_newest) FROM (
        SELECT service_name, max(arrayMax(timestamp_arr)) AS service_newest
        FROM posthog.metric_samples
        WHERE time_bucket >= toStartOfHour(now() - toIntervalHour(1)) AND time_bucket <= now()
        GROUP BY service_name
    )
    WHERE service_newest <= now() + toIntervalMinute(1)
    """
)


def fetch_metrics_freshness(team: Team, *, max_execution_time: int) -> dt.datetime | None:
    """The newest point the team's ingestion has written in the last hour, or None when it wrote none."""
    tag_queries(product=Product.METRICS, feature=Feature.ALERTING, source="metrics_alert", team_id=str(team.id))
    response = execute_hogql_query(
        query_type="metrics_alert_freshness",
        query=_TEAM_FRESHNESS_QUERY,
        team=team,
        workload=Workload.LOGS,
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
        settings=HogQLGlobalSettings(max_execution_time=max_execution_time, timeout_overflow_mode="throw"),
    )
    if not response.results or response.results[0][0] is None:
        return None
    freshness: dt.datetime = response.results[0][0]
    return freshness if freshness.tzinfo is not None else freshness.replace(tzinfo=ZoneInfo("UTC"))


def evaluation_time(due_at: dt.datetime, freshness: dt.datetime | None) -> dt.datetime:
    """The instant a check reads: its due time, held back to where ingestion has reached.

    Anchored on the due time rather than the clock, so a retried check sends the same query. Without
    a freshness the check reads at its due time, and the caller treats a missing series as unknown.
    """
    return due_at if freshness is None else min(due_at, freshness)
