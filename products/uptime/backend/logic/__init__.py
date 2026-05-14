from __future__ import annotations

import math
import re
import secrets
from datetime import date, datetime, timedelta
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.utils import IntegrityError
from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.redis import get_client

from ..facade.enums import PingOutcome
from ..models import Monitor, StatusPage

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


def update_monitor(*, team_id: int, monitor_id: UUID, name: str | None = None, url: str | None = None) -> Monitor:
    """Update a monitor's display name and/or URL. Pings are not rewritten — the monitor_id is stable.

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


def reorder_monitors(*, team_id: int, ordered_ids: list[UUID]) -> None:
    """Persist the user-controlled display order. The caller passes the new order as a list
    of monitor ids; each monitor's display_order is set to its position in that list.

    Unknown ids in the input are silently ignored (the auto-scope makes them invisible) so a
    concurrent delete doesn't crash the reorder. Monitors not present in `ordered_ids` keep
    their existing display_order.
    """
    with transaction.atomic():
        existing = {m.id: m for m in Monitor.objects.filter(id__in=ordered_ids)}
        for position, monitor_id in enumerate(ordered_ids):
            monitor = existing.get(monitor_id)
            if monitor is None:
                continue
            monitor.display_order = position
            monitor.save(update_fields=["display_order"])


def retrieve_monitor_summary(*, team_id: int, monitor_id: UUID) -> dict | None:
    """Single-monitor variant of list_monitor_summaries. Used by the detail page so it can fetch
    one row directly instead of pulling the whole list and filtering client-side."""
    summaries = list_monitor_summaries(team_id=team_id)
    return next((s for s in summaries if s["id"] == monitor_id), None)


def list_monitors() -> list[Monitor]:
    return list(Monitor.objects.order_by("display_order", "-created_at"))


def list_suggested_urls(*, team_id: int, days: int = 30, limit: int = 20) -> list[dict]:
    """Top pingable hosts from $pageview events, excluding hosts already monitored for the team.

    Returns one row per host with the canonical URL the user would monitor (always https origin),
    plus event/path counts and last-seen timestamp for ranking and display.
    """
    tag_queries(product=Product.UPTIME, team_id=team_id, feature=Feature.UPTIME_PINGS, name="list_suggested_urls")

    already_monitored_hosts: set[str] = set()
    for url in Monitor.objects.values_list("url", flat=True):
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


def _safe_float(value: object) -> float | None:
    """Coerce a ClickHouse aggregate result to float, treating None and NaN as None.

    ClickHouse's avgIf returns NaN (not None) when no rows match — common for new monitors
    that haven't been pinged yet, or windows with only failures. Without this, downstream
    `int(nan)` raises ValueError and the whole summary endpoint 500s.
    """
    if value is None:
        return None
    try:
        as_float = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(as_float):
        return None
    return as_float


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

    monitors = list(Monitor.objects.order_by("display_order", "-created_at"))
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
            "avg_latency": _safe_float(row[4]),
        }

    per_monitor_latest: dict[UUID, dict] = {}
    for row in latest_rows:
        monitor_id = UUID(str(row[0]))
        per_monitor_latest[monitor_id] = {
            "last_ping_at": row[1],
            "last_outcome": row[2],
            "avg_latency_24h": _safe_float(row[3]),
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


SLUG_RANDOM_BYTES = 4


def create_status_page(*, team_id: int) -> StatusPage:
    """Create a draft status page with a default title and a unique random slug.

    Clicking "New status page" in the UI lands the user directly in the editor — no naming modal —
    so we create with sensible defaults the user can edit in place.
    """
    title = "Untitled status page"
    return StatusPage.objects.create(
        team_id=team_id,
        title=title,
        slug=_generate_unique_slug(title),
        monitor_ids=[],
    )


def list_status_pages(*, team_id: int) -> list[StatusPage]:
    return list(StatusPage.objects.filter(team_id=team_id).order_by("-updated_at"))


def get_status_page(*, team_id: int, page_id: UUID) -> StatusPage:
    return StatusPage.objects.get(team_id=team_id, id=page_id)


def update_status_page(
    *,
    team_id: int,
    page_id: UUID,
    title: str | None = None,
    slug: str | None = None,
    monitor_ids: list[UUID] | None = None,
) -> StatusPage:
    page = StatusPage.objects.get(team_id=team_id, id=page_id)
    if title is not None:
        page.title = title
    if slug is not None and slug != page.slug:
        page.slug = _sanitize_slug(slug)
    if monitor_ids is not None:
        # Keep only monitor IDs that belong to this team — silently drop stale IDs so an orphan
        # never appears on the public page.
        valid_ids = set(Monitor.objects.filter(team_id=team_id, id__in=monitor_ids).values_list("id", flat=True))
        page.monitor_ids = [m_id for m_id in monitor_ids if m_id in valid_ids]
    try:
        page.save()
    except IntegrityError as exc:
        raise SlugAlreadyTakenError("Slug already taken") from exc
    return page


def publish_status_page(*, team_id: int, page_id: UUID) -> StatusPage:
    page = StatusPage.objects.get(team_id=team_id, id=page_id)
    page.is_published = True
    page.published_at = timezone.now()
    page.save()
    return page


def unpublish_status_page(*, team_id: int, page_id: UUID) -> StatusPage:
    page = StatusPage.objects.get(team_id=team_id, id=page_id)
    page.is_published = False
    page.save()
    return page


def delete_status_page(*, team_id: int, page_id: UUID) -> None:
    StatusPage.objects.filter(team_id=team_id, id=page_id).delete()


def get_public_status_page_view(*, slug: str) -> dict | None:
    """Return the publicly viewable status page payload (title, color, monitors + their summaries).

    Returns None if no published page matches the slug. Only published pages are exposed publicly.
    The page lookup bypasses team scoping (slug is globally unique and this endpoint is unauthenticated);
    the monitor summary call then runs inside the page's team scope so the fail-closed manager is happy.
    """
    page = StatusPage.objects.unscoped().filter(slug=slug, is_published=True).first()
    if page is None:
        return None
    with team_scope(page.team_id):
        summaries_by_id = {row["id"]: row for row in list_monitor_summaries(team_id=page.team_id)}
    monitors = [summaries_by_id[m_id] for m_id in page.monitor_ids if m_id in summaries_by_id]
    return {
        "title": page.title,
        "monitors": monitors,
        "published_at": page.published_at,
    }


class SlugAlreadyTakenError(Exception):
    pass


def _generate_unique_slug(title: str) -> str:
    """Generate a slug that's guaranteed unique across all status pages.

    Public URLs are unauthenticated and use the slug as the only key, so we can't rely on a
    composite unique constraint here.
    """
    base = _sanitize_slug(title) or "status-page"
    for _ in range(10):
        suffix = secrets.token_hex(SLUG_RANDOM_BYTES)
        candidate = f"{base}-{suffix}"
        if not StatusPage.objects.unscoped().filter(slug=candidate).exists():
            return candidate
    # Astronomically unlikely. If we get here something is very wrong; fall back to pure random.
    return secrets.token_hex(SLUG_RANDOM_BYTES * 2)


def _sanitize_slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:64]


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
