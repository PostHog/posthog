"""Ingestion freshness for metrics alerts.

A metrics alert must not read a window the pipeline has not finished writing: a gap would look
like recovery, or like no data. The Kafka consumer records the newest observed timestamp per
partition in `metrics_kafka_metrics`, and the slowest partition is the point every partition has
reached. The logs source applies the same rule from its own table.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team

# A partition that stopped receiving data pins the minimum in the past forever. Past this age the
# checkpoint is ignored so a quiet partition cannot strand every alert on the active ones.
CHECKPOINT_MAX_STALENESS = dt.timedelta(minutes=5)

LIVE_METRICS_CHECKPOINT_QUERY = parse_select(
    """
    SELECT minOrNull(partition_checkpoint) FROM (
        SELECT _topic, _partition, max(max_observed_timestamp) AS partition_checkpoint
        FROM posthog.metrics_kafka_metrics
        GROUP BY _topic, _partition
    )
    """
)


def fetch_live_metrics_checkpoint(team: Team) -> dt.datetime | None:
    tag_queries(
        product=Product.METRICS,
        feature=Feature.ALERTING,
        source="metrics_alert",
        team_id=str(team.id),
    )
    response = execute_hogql_query(
        query_type="metrics_alert_check_checkpoint",
        query=LIVE_METRICS_CHECKPOINT_QUERY,
        team=team,
        workload=Workload.LOGS,
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
    )
    if not response.results or response.results[0][0] is None:
        return None
    checkpoint = response.results[0][0]
    if checkpoint.tzinfo is None:
        checkpoint = checkpoint.replace(tzinfo=ZoneInfo("UTC"))
    return checkpoint


def resolve_alert_date_to(next_check_at: dt.datetime, checkpoint: dt.datetime | None) -> dt.datetime:
    """The window end a check may read: its due time, clamped to a fresh checkpoint."""
    if checkpoint is None or (next_check_at - checkpoint) > CHECKPOINT_MAX_STALENESS:
        return next_check_at
    return min(next_check_at, checkpoint)
