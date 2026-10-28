"""How far metrics ingestion has reached, so an alert never reads a window still being written.

A series the pipeline has not written yet is absent from an instant query, and an absent series
resolves its group. So a stalled consumer would read as recovery. The consumer records the newest
observed timestamp per partition, and the slowest partition is the point every partition reached.
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

# A partition that stopped receiving data pins the minimum in the past. Past this age the
# checkpoint is ignored, so one quiet partition cannot hold back every alert.
CHECKPOINT_MAX_STALENESS: Final = dt.timedelta(minutes=5)

_LIVE_METRICS_CHECKPOINT_QUERY: Final = parse_select(
    """
    SELECT minOrNull(partition_checkpoint) FROM (
        SELECT _topic, _partition, max(max_observed_timestamp) AS partition_checkpoint
        FROM metrics_kafka_metrics
        GROUP BY _topic, _partition
    )
    """
)


def fetch_live_metrics_checkpoint(team: Team, *, max_execution_time: int) -> dt.datetime | None:
    tag_queries(product=Product.METRICS, feature=Feature.ALERTING, source="metrics_alert", team_id=str(team.id))
    response = execute_hogql_query(
        query_type="metrics_alert_checkpoint",
        query=_LIVE_METRICS_CHECKPOINT_QUERY,
        team=team,
        workload=Workload.LOGS,
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
        settings=HogQLGlobalSettings(max_execution_time=max_execution_time, timeout_overflow_mode="throw"),
    )
    if not response.results or response.results[0][0] is None:
        return None
    checkpoint: dt.datetime = response.results[0][0]
    return checkpoint if checkpoint.tzinfo is not None else checkpoint.replace(tzinfo=ZoneInfo("UTC"))


def evaluation_time(due_at: dt.datetime, checkpoint: dt.datetime | None) -> dt.datetime:
    """The instant a check reads: its due time, held back to a fresh checkpoint.

    Anchored on the due time rather than the clock, so a retried check sends the same query.
    """
    if checkpoint is None or (due_at - checkpoint) > CHECKPOINT_MAX_STALENESS:
        return due_at
    return min(due_at, checkpoint)
