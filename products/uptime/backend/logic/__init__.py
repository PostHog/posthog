from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID

from django.db import transaction

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team.team import Team

from ..facade.enums import PingOutcome
from ..models import Monitor


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
