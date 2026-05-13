from __future__ import annotations

from datetime import datetime
from uuid import UUID

from posthog.clickhouse.client import sync_execute

from ..facade.enums import PingOutcome
from ..models import Monitor


def create_monitor(*, team_id: int, name: str, url: str) -> Monitor:
    return Monitor.objects.create(team_id=team_id, name=name, url=url)


def list_monitors() -> list[Monitor]:
    return list(Monitor.objects.order_by("-created_at"))


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


def list_recent_pings(*, team_id: int, monitor_id: UUID, limit: int = 50) -> list[dict]:
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
