"""Delivery health for cloud provider log sources, read from the ingestion metrics the logs
consumer writes per source."""

from datetime import UTC, datetime, timedelta

from django.db import models

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen

# app_metrics2 rows the logs consumer writes per source, keyed by instance_id = source id.
SOURCE_RECEIVED_METRIC = "source_records_received"
SOURCE_DROPPED_METRIC = "source_records_dropped"
HEALTH_WINDOW = timedelta(hours=24)
# app_metrics2 truncates timestamps to the hour, so "recent" has to allow a full bucket plus slack.
STALE_AFTER = timedelta(hours=2)


class LogsSourceHealthStatus(models.TextChoices):
    RECEIVING = "receiving", "Receiving"
    WAITING = "waiting", "Waiting for first delivery"
    STALE = "stale", "No recent data"
    DISABLED = "disabled", "Disabled"


@frozen
class SourceHealth:
    last_received_at: datetime | None
    records_received_24h: int
    records_dropped_24h: int

    def status(self, *, enabled: bool, now: datetime) -> LogsSourceHealthStatus:
        if not enabled:
            return LogsSourceHealthStatus.DISABLED
        if self.last_received_at is None:
            return LogsSourceHealthStatus.WAITING
        if now - self.last_received_at > STALE_AFTER:
            return LogsSourceHealthStatus.STALE
        return LogsSourceHealthStatus.RECEIVING

    def as_payload(self, *, enabled: bool, now: datetime) -> dict:
        return {
            "status": self.status(enabled=enabled, now=now),
            "last_received_at": self.last_received_at,
            "records_received_24h": self.records_received_24h,
            "records_dropped_24h": self.records_dropped_24h,
        }


NO_DELIVERIES = SourceHealth(last_received_at=None, records_received_24h=0, records_dropped_24h=0)


def fetch_sources_health(team_id: int, source_ids: list[str], now: datetime) -> dict[str, SourceHealth]:
    """One ClickHouse query for every source in the environment, so a sources list costs one round trip."""
    if not source_ids:
        return {}
    tag_queries(product=Product.LOGS, feature=Feature.QUERY, source="logs_sources_health", team_id=str(team_id))
    rows = sync_execute(
        """
        SELECT
            instance_id,
            maxOrNullIf(timestamp, metric_name = %(received)s),
            sumIf(count, metric_name = %(received)s),
            sumIf(count, metric_name = %(dropped)s)
        FROM app_metrics2
        WHERE team_id = %(team_id)s
          AND app_source = 'logs'
          AND app_source_id = ''
          AND instance_id IN %(instance_ids)s
          AND metric_name IN (%(received)s, %(dropped)s)
          AND timestamp >= toDateTime64(%(after)s, 6)
        GROUP BY instance_id
        """,
        {
            "team_id": team_id,
            "instance_ids": source_ids,
            "received": SOURCE_RECEIVED_METRIC,
            "dropped": SOURCE_DROPPED_METRIC,
            "after": (now - HEALTH_WINDOW).strftime("%Y-%m-%dT%H:%M:%S"),
        },
        team_id=team_id,
    )
    health: dict[str, SourceHealth] = {}
    for instance_id, last_received_at, received, dropped in rows or []:
        if last_received_at is not None and last_received_at.tzinfo is None:
            last_received_at = last_received_at.replace(tzinfo=UTC)
        health[str(instance_id)] = SourceHealth(
            last_received_at=last_received_at,
            records_received_24h=int(received or 0),
            records_dropped_24h=int(dropped or 0),
        )
    return health
