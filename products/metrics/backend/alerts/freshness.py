"""How far metrics ingestion has reached, so an alert never reads a window still being written.

A series the pipeline has not written yet is absent from an instant query, and an absent series
resolves its group. So a consumer lag would read as recovery. Two reads show how far ingestion has
reached. The newest point the team's services sent moves while any partition flows. The partition
checkpoint is the oldest of each Kafka partition's newest capture time, so it moves only when every
partition does.
"""

import datetime as dt
from contextlib import AbstractContextManager
from typing import Final
from zoneinfo import ZoneInfo

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import HogQLQueryExecutor
from posthog.hogql.visitor import clone_expr

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import (
    ClickHouseUser,
    Workload,
    connection_creds,
    get_kwargs_for_client,
    is_file_backed_user,
    make_ch_pool,
)
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team

# The shared pool's socket reads never time out, so a stalled connection would outlive the activity.
# The margin over the query's own limit lets the server's timeout error arrive first.
_TRANSPORT_MARGIN_SECONDS: Final = 5

# Reads the `service_freshness_by_hour` projection of `metrics4_samples`, one row per service-hour.
# The sender sets point times, so a service dated ahead is capped at now rather than dropped, which
# would let it push live services out and rewind every check. A team over 15 minutes behind gets none.
_TEAM_FRESHNESS_QUERY: Final = parse_select(
    """
    SELECT least(maxOrNull(service_newest), now()) FROM (
        SELECT service_name, max(arrayMax(timestamp_arr)) AS service_newest
        FROM posthog.metric_samples
        WHERE time_bucket >= toStartOfHour(now() - toIntervalHour(1)) AND time_bucket <= now() + toIntervalHour(1)
        GROUP BY service_name
    )
    WHERE service_newest >= now() - toIntervalMinute(15)
    """
)


# Not scoped to a team, because every team's samples spread over every partition. A floor more than
# 5 minutes old is a stalled partition or a dead writer, so it gets none.
_PARTITION_CHECKPOINT_QUERY: Final = parse_select(
    """
    SELECT least(min(partition_checkpoint), now()) AS checkpoint FROM (
        SELECT _topic, _partition, max(max_observed_timestamp) AS partition_checkpoint
        FROM posthog.metrics_kafka_metrics
        GROUP BY _topic, _partition
    )
    HAVING checkpoint >= now() - toIntervalMinute(5)
    """
)

# The checkpoint is a capture time, and a query reads by sample time. A sample reaches capture after
# its sender stamps it, so the read is held back by the sender delay to cover. 30s is the offset
# VictoriaMetrics reads with by default, so a sender slower than that is exposed here as in Grafana.
CHECKPOINT_EVAL_DELAY: Final = dt.timedelta(seconds=30)


def fetch_metrics_freshness(team: Team, *, max_execution_time: int) -> dt.datetime | None:
    """The newest point the team's ingestion has written, or None when it is more than 15 minutes behind."""
    return _fetch_instant(
        team, _TEAM_FRESHNESS_QUERY, query_type="metrics_alert_freshness", max_execution_time=max_execution_time
    )


def fetch_partition_checkpoint(team: Team, *, max_execution_time: int) -> dt.datetime | None:
    """The capture time every ingestion partition has passed, or None when it is more than 5 minutes behind."""
    return _fetch_instant(
        team,
        _PARTITION_CHECKPOINT_QUERY,
        query_type="metrics_alert_partition_checkpoint",
        max_execution_time=max_execution_time,
    )


def _fetch_instant(
    team: Team, query: ast.SelectQuery | ast.SelectSetQuery, *, query_type: str, max_execution_time: int
) -> dt.datetime | None:
    tag_queries(product=Product.METRICS, feature=Feature.ALERTING, source="metrics_alert", team_id=str(team.id))
    sql, context = HogQLQueryExecutor(
        query_type=query_type,
        # The executor edits the node it is given, and this one is shared by every call.
        query=clone_expr(query, True),
        team=team,
        workload=Workload.LOGS,
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
        settings=HogQLGlobalSettings(max_execution_time=max_execution_time, timeout_overflow_mode="throw"),
    ).generate_clickhouse_sql()
    with _bounded_logs_client(max_execution_time + _TRANSPORT_MARGIN_SECONDS) as client:
        rows = sync_execute(
            sql, context.values, workload=Workload.LOGS, team_id=team.id, readonly=True, sync_client=client
        )
    if not rows or rows[0][0] is None:
        return None
    instant: dt.datetime = rows[0][0]
    return instant if instant.tzinfo is not None else instant.replace(tzinfo=ZoneInfo("UTC"))


def _bounded_logs_client(send_receive_timeout: int) -> AbstractContextManager:
    """A logs cluster client whose socket reads and writes time out, as the shared pool's do not.

    Mirrors the file-backed branch of `get_pool`, so a token-authenticated user stays token-aware.
    `make_ch_pool` is cached on its arguments, so every call reuses one pool.
    """
    kwargs = get_kwargs_for_client(workload=Workload.LOGS, ch_user=ClickHouseUser.DEFAULT)
    creds = connection_creds(Workload.LOGS, ClickHouseUser.DEFAULT)
    if creds is not None and is_file_backed_user(creds, kwargs.get("user")):
        kwargs.pop("password", None)
        pool = make_ch_pool(
            send_receive_timeout=send_receive_timeout, credential_provider=creds.read_password, **kwargs
        )
    else:
        pool = make_ch_pool(send_receive_timeout=send_receive_timeout, **kwargs)
    return pool.get_client()


@frozen
class IngestionReach:
    """How far a team's ingestion has reached, from the two reads in this module.

    `checkpoint` is the capture time every partition has passed. When it is known, the newest point
    is not read.
    """

    checkpoint: dt.datetime | None
    newest_point: dt.datetime | None

    def evaluation_time(self, due_at: dt.datetime) -> dt.datetime:
        """The instant a check reads: its due time, held back to where ingestion has reached.

        Anchored on the due time rather than the clock, so a retried check sends the same query. A
        checkpoint is held back by `CHECKPOINT_EVAL_DELAY`, so every sample stamped before the instant
        is written. Without either read the check reads at its due time, and the caller treats a
        missing series as unknown.
        """
        if self.checkpoint is not None:
            return min(due_at, self.checkpoint - CHECKPOINT_EVAL_DELAY)
        return due_at if self.newest_point is None else min(due_at, self.newest_point)
