"""How far trace span ingestion has reached, so a traces alert never reads a window still being written."""

import datetime as dt
from typing import Final
from zoneinfo import ZoneInfo

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team

# The consumption table is not team-scoped, so the slowest partition bounds every team, as for logs.
_TRACES_CHECKPOINT_QUERY: Final = parse_select(
    """
    SELECT minOrNull(partition_checkpoint) FROM (
        SELECT _topic, _partition, max(max_observed_timestamp) AS partition_checkpoint
        FROM posthog.trace_spans_kafka_metrics
        GROUP BY _topic, _partition
    )
    """
)


def fetch_traces_checkpoint(
    team: Team, *, ch_user: ClickHouseUser = ClickHouseUser.DEFAULT, max_execution_time: int | None = None
) -> dt.datetime | None:
    """The newest span time every ingestion partition has passed, or None before any span arrived."""
    tag_queries(product=Product.TRACING, feature=Feature.ALERTING, source="traces_alert", team_id=str(team.id))
    response = execute_hogql_query(
        query_type="traces_alert_checkpoint",
        query=_TRACES_CHECKPOINT_QUERY,
        team=team,
        workload=Workload.LOGS,
        ch_user=ch_user,
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
        settings=None
        if max_execution_time is None
        else HogQLGlobalSettings(max_execution_time=max_execution_time, timeout_overflow_mode="throw"),
    )
    if not response.results or response.results[0][0] is None:
        return None
    checkpoint: dt.datetime = response.results[0][0]
    return checkpoint if checkpoint.tzinfo is not None else checkpoint.replace(tzinfo=ZoneInfo("UTC"))
