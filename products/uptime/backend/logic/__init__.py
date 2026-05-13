from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team.team import Team
from posthog.redis import get_client

from ..facade.enums import PingOutcome
from ..models import Monitor

logger = structlog.get_logger(__name__)

DailyStatus = Literal["up", "degraded", "down", "no_data"]
OverallStatus = Literal["up", "down", "no_data"]
DAILY_BUCKETS = 30

STATUS_UP = "up"
STATUS_DOWN = "down"
STATUS_UNKNOWN = "unknown"

STATUS_CHANGED_EVENT = "$uptime_monitor_status_changed"


def _status_redis_key(monitor_id: UUID) -> str:
    return f"uptime:monitor_status:{monitor_id}"


def _outcome_to_status(outcome: PingOutcome) -> str:
    return STATUS_UP if outcome == PingOutcome.SUCCESS else STATUS_DOWN


def create_monitor(*, team_id: int, name: str, url: str) -> Monitor:
    return Monitor.objects.create(team_id=team_id, name=name, url=url)


def bulk_create_monitors(*, team_id: int, items: list[dict[str, str]]) -> list[Monitor]:
    """Create monitors for several URLs atomically. Used by the URL-suggester bulk-add flow."""
    with transaction.atomic():
        return [Monitor.objects.create(team_id=team_id, name=item["name"], url=item["url"]) for item in items]


def list_monitors() -> list[Monitor]:
    return list(Monitor.objects.order_by("-created_at"))


def list_suggested_urls(*, team_id: int, days: int = 30, limit: int = 20) -> list[dict]:
    """Top pingable hosts from $pageview events, excluding hosts already monitored for the team.

    Returns one row per host with the canonical URL the user would monitor (always https origin),
    plus event/path counts and last-seen timestamp for ranking and display.
    """
    tag_queries(product=Product.UPTIME, team_id=team_id, feature=Feature.UPTIME_PINGS, name="list_suggested_urls")

    already_monitored_hosts: set[str] = set()
    for url in Monitor.objects.filter(team_id=team_id).values_list("url", flat=True):
        host = _host_from_url(url)
        if host:
            already_monitored_hosts.add(host.lower())

    team = Team.objects.get(pk=team_id)

    # We fetch more than `limit` so we can drop already-monitored hosts in Python without
    # under-filling the response. HogQL doesn't know about the Postgres Monitor table.
    overfetch = max(limit * 3, limit + len(already_monitored_hosts))

    response = execute_hogql_query(
        query="""
            SELECT
                properties.$host AS host,
                count() AS event_count,
                count(DISTINCT properties.$pathname) AS unique_paths,
                max(timestamp) AS last_seen
            FROM events
            WHERE event = '$pageview'
              AND timestamp > now() - INTERVAL {days} DAY
              AND properties.$host IS NOT NULL
              AND properties.$host != ''
              AND position(properties.$host, '.') > 0
              AND properties.$host NOT ILIKE 'localhost%'
              AND properties.$host NOT ILIKE '%.local'
              AND properties.$host NOT ILIKE '%.local:%'
              AND match(properties.$host, '^[0-9.]+(:[0-9]+)?$') = 0
            GROUP BY host
            ORDER BY event_count DESC
            LIMIT {limit}
        """,
        placeholders={
            "days": _int_constant(days),
            "limit": _int_constant(overfetch),
        },
        team=team,
    )

    rows: list[dict] = []
    for row in response.results or []:
        host = row[0]
        if not host:
            continue
        if host.lower() in already_monitored_hosts:
            continue
        rows.append(
            {
                "url": f"https://{host}",
                "host": host,
                "event_count": int(row[1]),
                "unique_paths": int(row[2]),
                "last_seen": row[3],
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _host_from_url(url: str) -> str:
    """Extract the host from a URL for comparison. Tolerates schemeless input."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.hostname or ""


def _int_constant(value: int) -> ast.Constant:
    return ast.Constant(value=value)


def get_monitor(*, monitor_id: UUID) -> Monitor:
    return Monitor.objects.get(id=monitor_id)


def record_ping(
    *,
    team_id: int,
    monitor_id: UUID,
    timestamp: datetime,
    latency_ms: int,
    status_code: int | None,
    outcome: PingOutcome,
) -> None:
    tag_queries(product=Product.UPTIME, team_id=team_id, feature=Feature.UPTIME_PINGS, name="record_ping")
    sync_execute(
        """
        INSERT INTO uptime_pings
        (team_id, monitor_id, timestamp, latency_ms, status_code, outcome)
        VALUES
        """,
        [
            {
                "team_id": team_id,
                "monitor_id": str(monitor_id),
                "timestamp": timestamp,
                "latency_ms": latency_ms,
                "status_code": status_code if status_code is not None else 0,
                "outcome": outcome.value,
            }
        ],
    )
    _maybe_emit_status_change(
        team_id=team_id,
        monitor_id=monitor_id,
        new_status=_outcome_to_status(outcome),
        timestamp=timestamp,
        latency_ms=latency_ms,
        status_code=status_code,
    )


def _maybe_emit_status_change(
    *,
    team_id: int,
    monitor_id: UUID,
    new_status: str,
    timestamp: datetime,
    latency_ms: int,
    status_code: int | None,
) -> None:
    redis_client = get_client()
    key = _status_redis_key(monitor_id)
    previous_raw = redis_client.get(key)
    if previous_raw is None:
        previous_status = STATUS_UNKNOWN
    elif isinstance(previous_raw, bytes):
        previous_status = previous_raw.decode()
    else:
        previous_status = previous_raw

    if previous_status == new_status:
        return

    redis_client.set(key, new_status)

    try:
        monitor = Monitor.objects.unscoped().filter(id=monitor_id).only("name", "url").first()
        if monitor is None:
            return
        produce_internal_event(
            team_id=team_id,
            event=InternalEventEvent(
                event=STATUS_CHANGED_EVENT,
                distinct_id=f"uptime_monitor_{monitor_id}",
                timestamp=timestamp.isoformat(),
                properties={
                    "monitor_id": str(monitor_id),
                    "monitor_name": monitor.name,
                    "monitor_url": monitor.url,
                    "previous_status": previous_status,
                    "new_status": new_status,
                    "status_code": status_code,
                    "latency_ms": latency_ms,
                },
            ),
        )
    except Exception:
        logger.exception("Failed to emit uptime monitor status changed event", monitor_id=str(monitor_id))


def list_monitor_summaries(*, team_id: int) -> list[dict]:
    """One row per monitor with current status, uptime %, latency, last ping, and 30 daily buckets.

    Pings are aggregated server-side in ClickHouse for the last 30 days. Monitors with no pings
    show status='no_data' and uptime/latency=None — the UI renders them as "no data yet" tiles.
    """
    tag_queries(product=Product.UPTIME, team_id=team_id, feature=Feature.UPTIME_PINGS, name="list_monitor_summaries")

    monitors = list(Monitor.objects.filter(team_id=team_id).order_by("-created_at"))
    if not monitors:
        return []

    daily_rows = sync_execute(
        """
        SELECT
            monitor_id,
            toDate(timestamp) AS day,
            count() AS total,
            countIf(outcome = 'failure') AS failed,
            avgIf(latency_ms, outcome = 'success') AS avg_latency
        FROM uptime_pings
        WHERE team_id = %(team_id)s
          AND timestamp > now() - INTERVAL 30 DAY
        GROUP BY monitor_id, day
        """,
        {"team_id": team_id},
    )

    latest_rows = sync_execute(
        """
        SELECT
            monitor_id,
            argMax(timestamp, timestamp) AS last_ping_at,
            argMax(outcome, timestamp) AS last_outcome,
            avgIf(latency_ms, outcome = 'success' AND timestamp > now() - INTERVAL 1 DAY) AS avg_latency_24h
        FROM uptime_pings
        WHERE team_id = %(team_id)s
        GROUP BY monitor_id
        """,
        {"team_id": team_id},
    )

    per_monitor_days: dict[UUID, dict[date, dict]] = {}
    for row in daily_rows:
        monitor_id = UUID(str(row[0]))
        day_value = row[1] if isinstance(row[1], date) else _to_date(row[1])
        per_monitor_days.setdefault(monitor_id, {})[day_value] = {
            "total": int(row[2]),
            "failed": int(row[3]),
            "avg_latency": float(row[4]) if row[4] is not None else None,
        }

    per_monitor_latest: dict[UUID, dict] = {}
    for row in latest_rows:
        monitor_id = UUID(str(row[0]))
        per_monitor_latest[monitor_id] = {
            "last_ping_at": row[1],
            "last_outcome": row[2],
            "avg_latency_24h": float(row[3]) if row[3] is not None else None,
        }

    today = timezone.now().astimezone(ZoneInfo("UTC")).date()
    day_window = [today - timedelta(days=i) for i in reversed(range(DAILY_BUCKETS))]

    summaries: list[dict] = []
    for monitor in monitors:
        days_for_monitor = per_monitor_days.get(monitor.id, {})
        latest = per_monitor_latest.get(monitor.id)

        daily_buckets: list[dict] = []
        total_pings = 0
        total_failed = 0
        for day_value in day_window:
            data = days_for_monitor.get(day_value)
            if data is None:
                daily_buckets.append({"date": day_value, "total": 0, "failed": 0, "status": "no_data"})
            else:
                total_pings += data["total"]
                total_failed += data["failed"]
                daily_buckets.append(
                    {
                        "date": day_value,
                        "total": data["total"],
                        "failed": data["failed"],
                        "status": _day_status(data["total"], data["failed"]),
                    }
                )

        uptime_30d = (total_pings - total_failed) / total_pings if total_pings else None

        if latest and latest["last_outcome"]:
            overall_status: OverallStatus = "up" if latest["last_outcome"] == PingOutcome.SUCCESS.value else "down"
            last_ping_at = latest["last_ping_at"]
            last_outcome = PingOutcome(latest["last_outcome"])
            avg_latency_24h = int(latest["avg_latency_24h"]) if latest["avg_latency_24h"] is not None else None
        else:
            overall_status = "no_data"
            last_ping_at = None
            last_outcome = None
            avg_latency_24h = None

        summaries.append(
            {
                "id": monitor.id,
                "name": monitor.name,
                "url": monitor.url,
                "created_at": monitor.created_at,
                "status": overall_status,
                "uptime_30d": uptime_30d,
                "avg_latency_24h_ms": avg_latency_24h,
                "last_ping_at": last_ping_at,
                "last_ping_outcome": last_outcome,
                "daily_buckets": daily_buckets,
            }
        )
    return summaries


def _day_status(total: int, failed: int) -> DailyStatus:
    if total == 0:
        return "no_data"
    if failed == 0:
        return "up"
    if failed >= total:
        return "down"
    return "degraded"


def _to_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value


def list_recent_pings(*, team_id: int, monitor_id: UUID, limit: int = 50) -> list[dict]:
    tag_queries(product=Product.UPTIME, team_id=team_id, feature=Feature.UPTIME_PINGS, name="list_recent_pings")
    rows = sync_execute(
        """
        SELECT monitor_id, timestamp, latency_ms, status_code, outcome
        FROM uptime_pings
        WHERE team_id = %(team_id)s AND monitor_id = %(monitor_id)s
        ORDER BY timestamp DESC
        LIMIT %(limit)s
        """,
        {"team_id": team_id, "monitor_id": str(monitor_id), "limit": limit},
    )
    return [
        {
            "monitor_id": UUID(str(row[0])),
            "timestamp": row[1],
            "latency_ms": int(row[2]),
            "status_code": int(row[3]) if row[3] else None,
            "outcome": PingOutcome(row[4]),
        }
        for row in rows
    ]
