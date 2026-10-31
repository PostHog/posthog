"""Read one user's own tasks, activity log rows and views in one project, from in-region Postgres,
and the calls of the user's MCP agent, from the Redis MCP intent buffer."""

import datetime
from collections.abc import Callable, Iterable

from django.conf import settings
from django.db.models.fields.json import KeyTextTransform, KeyTransform

import redis
import structlog

from posthog.dataclasses import frozen
from posthog.models import ActivityLog, FileSystem, FileSystemViewLog
from posthog.models.file_system.file_system import split_path
from posthog.redis import get_client

from products.dashboards.backend.facade.api import dashboards_by_insight
from products.signals.backend.activity_summary.mcp_buffer import count_key, parse_record, records_key, window_days
from products.signals.backend.activity_summary.render import (
    MAX_ACTIVITY_ROWS_PER_PERSON,
    MAX_TASKS_PER_PERSON,
    MAX_VIEW_ROWS_PER_PERSON,
    NOISY_ACTIVITY_SCOPES,
    SANDBOX_PROMPT_TITLE_PREFIX,
    SCENE_VIEW_TYPE,
    SCOUT_CLIENT_PREFIX,
    ActivityItem,
    McpItem,
    Parent,
    ParentLookup,
    TaskItem,
    ViewItem,
)
from products.tasks.backend.facade.user_task_summaries import list_user_task_summaries

# Tasks a person started: in PostHog AI, in Slack, or by hand in the web or desktop app. Scouts,
# reports and workflows start tasks under a person's name too, and those are not the person's intent.
TASK_ORIGIN_PRODUCTS = ("posthog_ai", "slack", "user_created")
# The build runs on a worker, not a request, so it can wait longer than the buffer's writer. A slow Redis
# must still not hold it up.
MCP_READ_TIMEOUT_SECONDS = 1.0

logger = structlog.get_logger(__name__)


def user_tasks(team_id: int, user_id: int, start: datetime.datetime, end: datetime.datetime) -> list[TaskItem]:
    """The user's own tasks in [start, end), newest `MAX_TASKS_PER_PERSON` first."""
    return [
        TaskItem(at=task.created_at, title=task.title, summary=task.summary, tags=task.tags)
        for task in list_user_task_summaries(
            team_ids=[team_id],
            user_id=user_id,
            start=start,
            end=end,
            origin_products=TASK_ORIGIN_PRODUCTS,
            limit=MAX_TASKS_PER_PERSON,
            exclude_title_prefixes=(SANDBOX_PROMPT_TITLE_PREFIX,),
        )
    ]


def user_activity(team_id: int, user_id: int, start: datetime.datetime, end: datetime.datetime) -> list[ActivityItem]:
    """The user's own activity log rows in [start, end), newest `MAX_ACTIVITY_ROWS_PER_PERSON` first.

    System rows and rows written while someone impersonated the user are not the user's. Noisy scopes
    and scout writes go before the limit, so a bulk write cannot push the rest of the window out."""
    rows = (
        ActivityLog.objects.filter(team_id=team_id, user_id=user_id, created_at__gte=start, created_at__lt=end)
        .exclude(is_system=True)
        .exclude(was_impersonated=True)
        .exclude(scope__in=NOISY_ACTIVITY_SCOPES)
        .exclude(client__startswith=SCOUT_CLIENT_PREFIX)
        .order_by("-created_at")
        .annotate(
            name=KeyTextTransform("name", "detail"),
            intent=KeyTextTransform("intent", KeyTransform("payload", KeyTransform("trigger", "detail"))),
            short_id=KeyTextTransform("short_id", "detail"),
        )
        .values(
            "scope", "activity", "client", "created_at", "name", "intent", "item_id", "credential_type", "short_id"
        )[:MAX_ACTIVITY_ROWS_PER_PERSON]
    )
    return [
        ActivityItem(
            at=row["created_at"],
            scope=row["scope"],
            activity=row["activity"],
            name=row["name"],
            client=row["client"],
            intent=row["intent"],
            item_id=row["item_id"],
            credential_type=row["credential_type"],
            short_id=row["short_id"],
        )
        for row in rows
    ]


def activity_parents(team_id: int, activity: Iterable[ActivityItem]) -> ParentLookup:
    """The dashboards that the insights in these rows sit on, in one query."""
    insight_ids = {
        int(item.item_id)
        for item in activity
        if item.scope == "Insight" and item.item_id and item.item_id.isascii() and item.item_id.isdigit()
    }
    if not insight_ids:
        return {}
    return {
        ("Insight", str(insight_id)): tuple(
            Parent(scope="Dashboard", item_id=str(dashboard.id), name=dashboard.name or "") for dashboard in dashboards
        )
        for insight_id, dashboards in dashboards_by_insight(insight_ids, team_id=team_id).items()
    }


def user_views(team_id: int, user_id: int, start: datetime.datetime, end: datetime.datetime) -> list[ViewItem]:
    """The objects and scenes the user last opened in [start, end), newest `MAX_VIEW_ROWS_PER_PERSON` first.

    A view log row keeps one object's latest view and the days of the views before it, so each item
    carries the days from `start` on. An object gets its name and creator from its file system entry."""
    rows = list(
        FileSystemViewLog.objects.filter(team_id=team_id, user_id=user_id, viewed_at__gte=start, viewed_at__lt=end)
        .exclude(type="folder")
        .order_by("-viewed_at")
        .values_list("type", "ref", "viewed_at", "view_days")[:MAX_VIEW_ROWS_PER_PERSON]
    )
    keys = {(view_type, ref) for view_type, ref, _, _ in rows if view_type != SCENE_VIEW_TYPE}
    entries: dict[tuple[str, str | None], tuple[str, int | None]] = {}
    if keys:
        for view_type, ref, path, creator_id in (
            FileSystem.objects.filter(
                team_id=team_id, type__in={key[0] for key in keys}, ref__in={key[1] for key in keys}
            )
            .exclude(shortcut=True)
            .values_list("type", "ref", "path", "created_by_id")
        ):
            if (view_type, ref) in keys and (segments := split_path(path)):
                entries[(view_type, ref)] = (segments[-1], creator_id)
    first_day = start.astimezone(datetime.UTC).date()
    items: list[ViewItem] = []
    for view_type, ref, viewed_at, view_days in rows:
        days = {day for day in view_days or () if day >= first_day} or {viewed_at.astimezone(datetime.UTC).date()}
        name, created_by_id = entries.get((view_type, ref), (None, None))
        items.append(
            ViewItem(
                at=viewed_at,
                type=view_type,
                ref=ref,
                name=name,
                days=tuple(sorted(days)),
                not_theirs=created_by_id is not None and created_by_id != user_id,
            )
        )
    return items


@frozen
class McpRead:
    """The buffered MCP calls of one user in one project, oldest first, and what the read saw."""

    records: tuple[McpItem, ...] = ()
    # Days whose count is above the length of the stored list: the buffer kept only their latest calls.
    truncated_days: int = 0
    read_error: bool = False


def _mcp_redis_client() -> redis.Redis:
    return get_client(
        settings.ACTIVITY_SUMMARY_MCP_BUFFER_REDIS_URL or None,
        socket_timeout=MCP_READ_TIMEOUT_SECONDS,
        socket_connect_timeout=MCP_READ_TIMEOUT_SECONDS,
    )


def user_mcp_records(
    team_id: int,
    user_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
    *,
    max_days: int,
    redis_client: Callable[[], redis.Redis] = _mcp_redis_client,
) -> McpRead:
    """The user's buffered MCP calls in [start, end), from the newest `max_days` UTC days, in one pipeline.

    The buffer is optional context, so this never raises: a failed read returns no records and sets
    `read_error`, and the build goes on with the other sources."""
    if end <= start:
        return McpRead()
    days = window_days(start, end, max_days)
    try:
        pipeline = redis_client().pipeline(transaction=False)
        for day in days:
            pipeline.lrange(records_key(team_id, user_id, day), 0, -1)
        pipeline.mget([count_key(team_id, user_id, day) for day in days])
        *lists, counts = pipeline.execute()
    except Exception:
        logger.warning("activity_summary.mcp_buffer_read_failed", team_id=team_id, user_id=user_id, exc_info=True)
        return McpRead(read_error=True)
    records: list[McpItem] = []
    truncated_days = 0
    for values, count in zip(lists, counts):
        try:
            total = int(count or 0)
        except ValueError:
            total = 0
        truncated_days += total > len(values)
        for value in values:
            record = parse_record(value)
            if record is not None and start <= record.at < end:
                records.append(record)
    return McpRead(records=tuple(records), truncated_days=truncated_days)
