from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from django.utils import timezone

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from ..facade.enums import PingOutcome
from ..models import Monitor

logger = structlog.get_logger(__name__)

DailyStatus = Literal["up", "degraded", "down", "no_data"]
OverallStatus = Literal["up", "down", "no_data"]
DAILY_BUCKETS = 90
OUTAGE_DEFAULT_DAYS = 7


def create_monitor(*, team_id: int, name: str, url: str) -> Monitor:
    return Monitor.objects.create(team_id=team_id, name=name, url=url)


def update_monitor(
    *,
    team_id: int,
    monitor_id: UUID,
    name: str | None = None,
    url: str | None = None,
) -> Monitor:
    """Update a monitor's display name and/or URL. Pings are not rewritten — the
    monitor_id is stable, so prior ping history carries over.

    The team_id param is unused at the query level — the manager auto-scopes by the canonical
    team in the request scope. Pinning to a raw team_id can miss rows when the URL's project_id
    differs from the canonical team_id the row was actually saved under.
    """
    monitor = Monitor.objects.get(id=monitor_id)
    if name is not None:
        monitor.name = name
    if url is not None:
        monitor.url = url
    monitor.save()
    return monitor


def delete_monitor(*, team_id: int, monitor_id: UUID) -> None:
    """Delete a monitor. Historical pings in uptime_pings are intentionally retained for audit;
    the monitor_id is a UUID so there's no reuse risk."""
    Monitor.objects.filter(id=monitor_id).delete()


def get_monitor(*, monitor_id: UUID) -> Monitor:
    return Monitor.objects.get(id=monitor_id)


def list_monitors() -> list[Monitor]:
    return list(Monitor.objects.order_by("-created_at"))


def retrieve_monitor_summary(*, team_id: int, monitor_id: UUID) -> dict | None:
    """Single-monitor variant of list_monitor_summaries. Used by the detail page so it can fetch
    one row directly instead of pulling the whole list and filtering client-side."""
    summaries = list_monitor_summaries(team_id=team_id)
    return next((s for s in summaries if s["id"] == monitor_id), None)


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


def list_monitor_summaries(*, team_id: int) -> list[dict]:
    """One row per monitor with current status, uptime %, latency, last ping, and 90 daily buckets.

    Pings are aggregated in ClickHouse and status / uptime / latency are derived from them.
    Monitors with no pings show status='no_data'.
    """
    tag_queries(product=Product.UPTIME, team_id=team_id, feature=Feature.UPTIME_PINGS, name="list_monitor_summaries")

    monitors = list(Monitor.objects.order_by("-created_at"))
    if not monitors:
        return []

    now_utc = timezone.now().astimezone(ZoneInfo("UTC"))
    today = now_utc.date()
    day_window = [today - timedelta(days=i) for i in reversed(range(DAILY_BUCKETS))]

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
          AND timestamp > now() - INTERVAL 90 DAY
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
    per_monitor_latest: dict[UUID, dict] = {}

    for row in daily_rows:
        monitor_id = UUID(str(row[0]))
        day_value = row[1] if isinstance(row[1], date) else _to_date(row[1])
        per_monitor_days.setdefault(monitor_id, {})[day_value] = {
            "total": int(row[2]),
            "failed": int(row[3]),
            "avg_latency": _safe_float(row[4]),
        }

    for row in latest_rows:
        monitor_id = UUID(str(row[0]))
        per_monitor_latest[monitor_id] = {
            "last_ping_at": row[1],
            "last_outcome": row[2],
            "avg_latency_24h": _safe_float(row[3]),
        }

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

        uptime_90d = (total_pings - total_failed) / total_pings if total_pings else None

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
                "uptime_90d": uptime_90d,
                "avg_latency_24h_ms": avg_latency_24h,
                "last_ping_at": last_ping_at,
                "last_ping_outcome": last_outcome,
                "daily_buckets": daily_buckets,
            }
        )
    return summaries


def list_outages_for_monitor(*, team_id: int, monitor_id: UUID, days: int = OUTAGE_DEFAULT_DAYS) -> list[dict]:
    """Detect outages from raw pings: a contiguous run of failures bounded by the first
    success that follows. An open run (no trailing success) is an ongoing outage."""
    tag_queries(product=Product.UPTIME, team_id=team_id, feature=Feature.UPTIME_PINGS, name="list_outages_for_monitor")
    rows = sync_execute(
        """
        SELECT timestamp, status_code, outcome
        FROM uptime_pings
        WHERE team_id = %(team_id)s
          AND monitor_id = %(monitor_id)s
          AND timestamp > now() - INTERVAL %(days)s DAY
        ORDER BY timestamp ASC
        """,
        {"team_id": team_id, "monitor_id": str(monitor_id), "days": days},
    )

    outages: list[dict] = []
    current: dict | None = None
    for row in rows:
        timestamp, status_code, outcome = row[0], row[1], row[2]
        if outcome == PingOutcome.FAILURE.value:
            if current is None:
                current = {
                    "started_at": timestamp,
                    "resolved_at": None,
                    "fail_count": 1,
                    "last_status_code": int(status_code) if status_code else None,
                }
            else:
                current["fail_count"] += 1
                if status_code:
                    current["last_status_code"] = int(status_code)
        elif current is not None:
            current["resolved_at"] = timestamp
            outages.append(current)
            current = None
    if current is not None:
        outages.append(current)

    outages.sort(key=lambda o: (o["resolved_at"] is not None, -o["started_at"].timestamp()))
    return [{"monitor_id": monitor_id, **o} for o in outages]


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


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN — avgIf over zero rows
        return None
    return result
