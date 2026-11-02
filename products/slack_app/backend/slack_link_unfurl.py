"""Slack link unfurling for PostHog resource URLs.

Ticket subjects and messages are customer-authored, so every one goes through `escape_slack_mrkdwn`.
"""

from __future__ import annotations

import re
import json
import asyncio
import dataclasses
from collections.abc import Callable
from datetime import datetime
from typing import Literal, cast
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlsplit, urlunsplit
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models.functions import Substr
from django.utils import timezone

import structlog
from slack_sdk.errors import SlackApiError
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.models.comment import Comment
from posthog.models.integration import SlackIntegration
from posthog.models.user_integration import UserIntegration
from posthog.object_tags.kinds import OBJECT_URL_TEMPLATES, ObjectRef, object_ref_for_url
from posthog.redis import get_client
from posthog.slack.formatting import escape_slack_mrkdwn
from posthog.temporal.common.client import sync_connect
from posthog.utils import get_instance_region

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import (
    UserAccessControl,
    access_level_satisfied_for_resource,
)
from products.canvas.backend.facade import access as canvas_access
from products.cohorts.backend.models.cohort import Cohort
from products.conversations.backend.models.ticket import Ticket
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.error_tracking.backend.facade import api as error_tracking_facade
from products.experiments.backend.facade import (
    api as experiments_facade,
    slack as experiments_slack,
)
from products.experiments.backend.facade.contracts import StoredArmResult, StoredPrimaryResult
from products.exports.backend.facade import api as exports_facade
from products.feature_flags.backend.facade.config import ConfigFormatError
from products.feature_flags.backend.facade.filters import condition_rollout_percentage
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.models import SignalReport
from products.signals.backend.report_access import may_read_reports
from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.feature_tips.features import SlackFeature
from products.slack_app.backend.logic.feature_tips.state import record_feature_used
from products.slack_app.backend.logic.link_unfurl_charts import (
    UNFURL_IMAGE_ASSET_TTL,
    UNFURL_IMAGE_URL_TTL,
    chat_unfurl_kwargs,
    has_project_access,
    slack_fetchable_image_url,
    with_chart_images,
)
from products.slack_app.backend.models import SlackThreadTaskMapping
from products.slack_app.backend.services.followup_invite import build_followup_invite
from products.slack_app.backend.services.slack_messages import UNFURL_OPT_OUT_PARAM
from products.slack_app.backend.services.slack_user_info import get_cached_bot_user_id
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration
from products.slack_app.backend.temporal.slack_app_unfurl_charts import (
    SLACK_APP_UNFURL_CHARTS_WORKFLOW_TIMEOUT,
    SlackAppUnfurlChartsWorkflow,
)
from products.slack_app.backend.temporal.types import SlackAppUnfurlChartsWorkflowInputs, SlackUnfurlChartRequest
from products.surveys.backend.models import Survey
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskSlackUnfurlDTO

logger = structlog.get_logger(__name__)

# Keep title + status + message under Slack's 3000-char section limit; the client shows "Show more".
_MAX_BODY_CHARS = 200
_MAX_TITLE_CHARS = 150
_MAX_DETAIL_CHARS = 100
_MAX_LINK_CHARS = 1000
_MAX_CHART_LINES = 4
_DATE_RANGE_UNITS = {"h": "hour", "d": "day", "w": "week", "m": "month", "y": "year"}
_NAMED_DATE_RANGES = {"dStart": "Today", "mStart": "This month", "yStart": "This year", "all": "All time"}
_MAX_GRID_TILES = 6
_CHART_WIDTH = 20
_CHART_LABEL_CHARS = 16

ADHOC_INSIGHT_KIND = "adhoc_insight"
TASK_ARTIFACT_KIND = "task_artifact"

_SLACK_IMAGE_CONTENT_TYPES = frozenset({"image/png", "image/jpeg", "image/gif"})
_MAX_ARTIFACT_IMAGE_BYTES = 5 * 1024 * 1024
_TASK_ARTIFACT_PATH = re.compile(
    r"/api/projects/(?P<project>[^/]+)/tasks/(?P<task>[^/]+)/runs/(?P<run>[^/]+)/artifacts/(?P<artifact>[^/]+)/"
)

_UNFURL_TEMPLATES: dict[str, tuple[str, ...]] = {
    "insight": (*OBJECT_URL_TEMPLATES["insight"], "/bi/{id}"),
    "dashboard": OBJECT_URL_TEMPLATES["dashboard"],
    "ticket": OBJECT_URL_TEMPLATES["ticket"],
    "task": ("/tasks/{id}", "/code/task/{id}", "/code/channel/{channel}/tasks/{id}", "/ai?task={id}"),
    "canvas": ("/canvases/{id}", "/code/canvas/{channel}/{id}"),
    "notebook": ("/notebooks/{id}",),
    "flag": OBJECT_URL_TEMPLATES["flag"],
    "experiment": OBJECT_URL_TEMPLATES["experiment"],
    "survey": OBJECT_URL_TEMPLATES["survey"],
    "cohort": OBJECT_URL_TEMPLATES["cohort"],
    "error": OBJECT_URL_TEMPLATES["error"],
    "report": ("/inbox/{tab}/{id}", *OBJECT_URL_TEMPLATES["report"]),
}

_KIND_EMOJI: dict[str, str] = {
    "insight": "📈",
    "dashboard": "📊",
    "ticket": "🎫",
    "task": "🤖",
    TASK_ARTIFACT_KIND: "📎",
    "canvas": "🎨",
    "notebook": "📓",
    "flag": "🚩",
    "experiment": "🧪",
    "survey": "📝",
    "cohort": "👥",
    "error": "🐞",
    ADHOC_INSIGHT_KIND: "📈",
}

# A kind with a product logo shows it in the card summary instead of an emoji in the title.
_KIND_ICON_PATH: dict[str, str] = {
    "report": "/static/icons/self-driving.png",
}

_SkipReason = Literal["not_found", "no_access", "other_project", "not_found_or_no_access", "public_sharing_disabled"]

_REJECTED_PAYLOAD_ERRORS = frozenset(
    {"cannot_parse_attachment", "invalid_unfurls_format", "invalid_arguments", "invalid_array_arg", "invalid_blocks"}
)

_INVITE_UTM_TAGS = "utm_source=slack&utm_medium=unfurl&utm_campaign=link_unfurl_followup"
# A channel that shares PostHog links all day would otherwise carry the invite on every unfurl,
# which reads as chrome and stops being noticed. One a day per channel keeps it legible.
_INVITE_THROTTLE_SECONDS = 24 * 60 * 60
# The throttle must fail fast rather than correctly: it sits inside the webhook's ack budget.
_INVITE_REDIS_TIMEOUT_SECONDS = 0.3

# Query `source.kind` / top-level `kind` → short name before " insight" (sync with InsightType / query kinds).
_QUERY_KIND_TO_SHORT_NAME: dict[str, str] = {
    "TrendsQuery": "Trends",
    "FunnelsQuery": "Funnel",
    "RetentionQuery": "Retention",
    "PathsQuery": "Paths",
    "PathsV2Query": "Journeys",
    "StickinessQuery": "Stickiness",
    "LifecycleQuery": "Lifecycle",
    "WebStatsTableQuery": "Web analytics",
    "WebOverviewQuery": "Web analytics",
    "HogQLQuery": "SQL",
    "HogQuery": "Hog",
}

# Legacy `filters.insight` string (see InsightType in frontend).
_LEGACY_FILTER_INSIGHT_TO_SHORT_NAME: dict[str, str] = {
    "TRENDS": "Trends",
    "STICKINESS": "Stickiness",
    "LIFECYCLE": "Lifecycle",
    "FUNNELS": "Funnel",
    "PATHS": "Paths",
    "RETENTION": "Retention",
    "JSON": "JSON",
    "SQL": "SQL",
    "HOG": "Hog",
    "WEB_ANALYTICS": "Web analytics",
    "SESSIONS": "Sessions",
}


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    cut = text[: max_len - 1]
    word_end = cut.rfind(" ")
    return (cut[:word_end] if word_end > max_len // 2 else cut).rstrip(" ,.;:") + "…"


# App hosts that name a Cloud region. `app.posthog.com` is the legacy alias for US Cloud; a bare
# `posthog.com` link names no region at all.
_APP_HOST_REGIONS: dict[str, str] = {
    "us.posthog.com": "US",
    "app.posthog.com": "US",
    "eu.posthog.com": "EU",
}


def link_url_region(url: str) -> str | None:
    """The Cloud region a link's host names, or None when the host doesn't say."""
    return _APP_HOST_REGIONS.get(urlparse(url).hostname or "")


def adhoc_insight_query(url: str) -> dict | None:
    raw = parse_qs(urlparse(url).fragment).get("q")
    if not raw:
        return None
    try:
        query = json.loads(raw[0])
    except ValueError:
        return None
    return query if isinstance(query, dict) else None


def _is_adhoc_insight_url(url: str) -> bool:
    segments = [segment for segment in urlparse(url).path.split("/") if segment]
    if segments[:1] == ["project"]:
        segments = segments[2:]
    return segments[:2] == ["insights", "new"] and adhoc_insight_query(url) is not None


def parse_posthog_resource_link(url: str) -> ObjectRef | None:
    """
    Parse a PostHog app URL into the object a card can unfurl.

    An unsaved insight link (`/insights/new#q=<query>`) has the id "new", so logs never carry its
    query. Read the query with `adhoc_insight_query`.

    A URL carrying `?unfurl=false` is not a resource here: links we post ourselves already
    sit beside the detail a card would add, so they opt out rather than repeat it.

    If the path includes `/project/:id`, that segment is ignored — lookup is always scoped to the
    Slack-connected project and the resolved PostHog user, not to any project id in the URL.
    """
    if "false" in parse_qs(urlparse(url).query).get(UNFURL_OPT_OUT_PARAM, []):
        return None
    if _is_adhoc_insight_url(url):
        return ObjectRef(kind=ADHOC_INSIGHT_KIND, id="new")
    artifact_ref = _task_artifact_ref(url)
    if artifact_ref is not None:
        return ObjectRef(kind=TASK_ARTIFACT_KIND, id=artifact_ref.artifact_id or artifact_ref.name or "")
    return object_ref_for_url(url, _UNFURL_TEMPLATES)


def _extract_query_source_kind(query: dict) -> str | None:
    """Return the inner query kind (e.g. TrendsQuery, HogQLQuery) for labeling; no DB access."""
    kind = query.get("kind")
    if not isinstance(kind, str):
        return None

    source = query.get("source")
    source = source if isinstance(source, dict) else None

    if kind == "InsightVizNode" and source:
        return source.get("kind") if isinstance(source.get("kind"), str) else None

    if kind in ("DataVisualizationNode", "DataTableNode") and source:
        sk = source.get("kind")
        if sk == "HogQLQuery":
            return "HogQLQuery"
        if sk == "InsightVizNode":
            nested = source.get("source")
            if isinstance(nested, dict) and isinstance(nested.get("kind"), str):
                return nested.get("kind")
        if isinstance(sk, str):
            return sk

    if kind == "HogQLQuery":
        return "HogQLQuery"
    if kind == "HogQuery":
        return "HogQuery"

    if kind in _QUERY_KIND_TO_SHORT_NAME:
        return kind

    return None


def _query_resource_label(query: dict) -> str | None:
    inner = _extract_query_source_kind(query)
    if not inner:
        return None
    short = _QUERY_KIND_TO_SHORT_NAME.get(inner)
    if short:
        return f"{short} insight"
    if inner.endswith("Query"):
        return f"{inner[: -len('Query')]} insight"
    return f"{inner} insight"


def _insight_resource_label(insight: Insight) -> str:
    """e.g. 'Trends insight', 'SQL insight' — from query JSON or legacy filters only (no execution)."""
    q = insight.query
    if isinstance(q, dict) and q:
        label = _query_resource_label(q)
        if label:
            return label

    filters = insight.filters if isinstance(insight.filters, dict) else {}
    legacy = filters.get("insight")
    if isinstance(legacy, str):
        short = _LEGACY_FILTER_INSIGHT_TO_SHORT_NAME.get(legacy)
        if short:
            return f"{short} insight"

    return "Insight"


def _url_team_id(url: str) -> int | None:
    """The team id from a `/project/:id/...` URL segment, if present (matches middleware behavior)."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "project" and parts[1].isdigit():
        return int(parts[1])
    return None


def _find_ticket(team_id: int, ref: str) -> Ticket | None:
    """Resolve a ticket by its human number or UUID, scoped to the team."""
    if ref.isdigit():
        return Ticket.objects.filter(team_id=team_id, ticket_number=int(ref)).first()
    try:
        return Ticket.objects.filter(team_id=team_id, pk=ref).first()
    except (ValueError, ValidationError):
        return None


def _ticket_requester(team: Team, ticket: Ticket) -> str:
    """Display the ticket's requester using the project's person display-name settings.

    The ticket's ``anonymous_traits`` are the customer-provided person properties, so we pick the
    first configured display property present (default order prefers email), then fall back.
    """
    # Deferred to keep the heavy posthog.api.person module off the Django startup import path.
    from posthog.api.person import PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES  # noqa: PLC0415

    traits = ticket.anonymous_traits or {}
    for prop in team.person_display_name_properties or PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES:
        value = traits.get(prop)
        if value:
            return str(value)
    return ticket.email_from or "Anonymous"


def _ticket_opening_message(team_id: int, ticket_id: UUID) -> str | None:
    """The ticket's opening public message: the earliest non-private, non-deleted conversations_ticket comment.

    Private/internal notes (``item_context.is_private``) and soft-deleted comments are excluded so
    neither surfaces in Slack.
    """
    content = (
        Comment.objects.filter(team_id=team_id, scope="conversations_ticket", item_id=str(ticket_id), deleted=False)
        .exclude(item_context__is_private=True)
        .order_by("created_at")
        .values_list("content", flat=True)
        .first()
    )
    return content


@frozen
class _CardButton:
    label: str
    url: str


@frozen
class _TaskArtifactRef:
    project_id: int | None
    task_id: UUID
    run_id: UUID | None = None
    artifact_id: str | None = None
    name: str | None = None


def _task_artifact_ref(url: str) -> _TaskArtifactRef | None:
    """A task artifact named by its download link, or by its place in the task's Artifacts tab."""
    parsed = urlparse(url)
    match = _TASK_ARTIFACT_PATH.search(parsed.path)
    if match:
        task_id, run_id = _uuid(match["task"]), _uuid(match["run"])
        if task_id is None or run_id is None:
            return None
        project = match["project"]
        return _TaskArtifactRef(
            project_id=int(project) if project.isdigit() else None,
            task_id=task_id,
            run_id=run_id,
            artifact_id=match["artifact"],
        )
    segments = [segment for segment in parsed.path.split("/") if segment]
    params = parse_qs(parsed.query)
    if (segments[2:] if segments[:1] == ["project"] else segments) != ["ai"] or "artifact" not in params:
        return None
    task_id = _uuid(params.get("task", [""])[0])
    if task_id is None:
        return None
    return _TaskArtifactRef(
        project_id=_url_team_id(url),
        task_id=task_id,
        artifact_id=params.get("artifact_version", [None])[0],
        name=params["artifact"][0],
    )


@frozen
class _UnfurlCard:
    label: str
    title: str
    status: str | None = None
    details: tuple[str, ...] = ()
    body: str | None = None
    chart: str | None = None
    timestamp: datetime | None = None
    timestamp_label: str = "Updated"
    button: _CardButton | None = None
    chart_insight_id: int | None = None
    # Set for a saved insight link with unsaved edits. The chart renders this query instead of the saved one.
    chart_edited_query: dict | None = None
    # Set for an ad hoc insight. Its card goes out only together with its chart.
    chart_query: dict | None = None
    artifact_image: bool = False
    # Set when the shared link is not the page that shows the resource, such as a file download.
    open_url: str | None = None


def _tracked_url(url: str, kind: str) -> str:
    parts = urlsplit(url)
    for trimmed in ("fragment", "query"):
        if len(urlunsplit(parts)) > _MAX_LINK_CHARS:
            parts = parts._replace(**{trimmed: ""})
    params = [*parse_qsl(parts.query), ("utm_source", "slack"), ("utm_medium", "unfurl"), ("utm_content", kind)]
    return urlunsplit(parts._replace(query=urlencode(params)))


def _card_summary(card: _UnfurlCard, *, compact: bool) -> str:
    parts = [escape_slack_mrkdwn(card.label)]
    if card.status:
        parts.append(f"*{escape_slack_mrkdwn(card.status)}*")
    if not compact:
        parts.extend(escape_slack_mrkdwn(_truncate(detail, _MAX_DETAIL_CHARS)) for detail in card.details)
    if card.timestamp:
        label = card.timestamp_label
        parts.append(f"<!date^{int(card.timestamp.timestamp())}^{label} {{ago}}|{label} {card.timestamp:%Y-%m-%d}>")
    return "  ·  ".join(parts)


def _card_blocks(card: _UnfurlCard, *, kind: str, url: str, compact: bool) -> list[dict]:
    link = _tracked_url(card.open_url or url, kind)
    title = f"*<{link}|{escape_slack_mrkdwn(_truncate(card.title, _MAX_TITLE_CHARS))}>*"
    summary: list[dict] = [{"type": "mrkdwn", "text": _card_summary(card, compact=compact)}]
    icon_path = _KIND_ICON_PATH.get(kind)
    if icon_path:
        icon_url = slack_fetchable_image_url(f"{settings.SITE_URL}{icon_path}")
        summary.insert(0, {"type": "image", "image_url": icon_url, "alt_text": card.label})
    else:
        title = f"{_KIND_EMOJI[kind]}  {title}"
    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": title}},
        {"type": "context", "elements": summary},
    ]
    if compact:
        return blocks
    if card.chart:
        chart = f"```{escape_slack_mrkdwn(card.chart)}```"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chart}})
    body = (card.body or "").strip()
    if body:
        text = _truncate(escape_slack_mrkdwn(body), _MAX_BODY_CHARS)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
    buttons = [{"type": "button", "text": {"type": "plain_text", "text": "Open in PostHog"}, "url": link}]
    if card.button:
        buttons.append(
            {"type": "button", "text": {"type": "plain_text", "text": card.button.label}, "url": card.button.url}
        )
    blocks.append({"type": "actions", "elements": buttons})
    return blocks


def _claim_invite_slot(slack_team_id: str, channel: str) -> bool:
    """Whether this channel may carry the follow-up invite now, claiming the day's slot if so.

    ``SET NX EX`` makes the claim atomic, so two unfurls racing in the same channel produce one
    invite. A Redis failure returns False: skipping a nudge costs nothing, while failing open
    would turn an outage into an invite on every unfurl in every channel at once.

    The raw client rather than ``cache.add``, which the product's other one-shot claims use,
    because this one needs an explicit timeout. ``CACHES`` sets no ``SOCKET_TIMEOUT``, so a cache
    call waits on a stalled Redis for as long as it takes, and the ack budget does not allow that.
    """
    try:
        client = get_client(
            socket_timeout=_INVITE_REDIS_TIMEOUT_SECONDS,
            socket_connect_timeout=_INVITE_REDIS_TIMEOUT_SECONDS,
        )
        claimed = client.set(
            f"slack_app:unfurl_invite:v1:{slack_team_id}:{channel}",
            "1",
            nx=True,
            ex=_INVITE_THROTTLE_SECONDS,
        )
    except Exception:
        logger.warning("slack_app_unfurl_invite_throttle_unavailable", channel=channel, exc_info=True)
        return False
    return bool(claimed)


def _build_unfurl_invite(integration: WorkspaceIntegration, kind: str, channel: str) -> dict | None:
    """The invite block for the first resource we unfurled, or None when it should stay quiet.

    Consent is checked before the slot is claimed: the other way round, a workspace that never
    approved AI would burn its channel's daily slot on every paste, and an approval later that
    day would stay suppressed until the key expired.
    """
    slack_team_id = integration.integration_id
    if not slack_team_id:
        return None
    ai_enabled = bool(integration.team.organization.is_ai_data_processing_approved)
    if not ai_enabled:
        return None
    if not _claim_invite_slot(slack_team_id, channel):
        return None
    return build_followup_invite(
        integration,
        utm_tags=_INVITE_UTM_TAGS,
        ai_enabled=ai_enabled,
        subject=f"this {kind.replace('_', ' ')}",
    )


def _is_normal_public_channel(slack: SlackIntegration, channel: str, cache: dict[str, bool]) -> bool:
    if channel in cache:
        return cache[channel]
    try:
        conversation = slack.client.conversations_info(channel=channel).get("channel") or {}
    except Exception:
        logger.exception("slack_task_reference_channel_lookup_failed", channel=channel)
        cache[channel] = False
        return False
    cache[channel] = bool(
        conversation.get("is_channel")
        and not conversation.get("is_private")
        and not conversation.get("is_shared")
        and not conversation.get("is_ext_shared")
        and not conversation.get("is_org_shared")
    )
    return cache[channel]


def _task_owner_can_view_public_slack_channel(
    slack: SlackIntegration,
    integration: WorkspaceIntegration,
    task: TaskSlackUnfurlDTO,
    cache: dict[str, bool],
) -> bool:
    if task.created_by_id is None:
        return False
    owner_link = (
        UserIntegration.objects.filter(
            user_id=task.created_by_id,
            kind=UserIntegration.IntegrationKind.SLACK,
            config__slack_team_id=integration.integration_id,
        )
        .order_by("-created_at")
        .first()
    )
    if owner_link is None:
        return False
    if owner_link.integration_id in cache:
        return cache[owner_link.integration_id]
    try:
        owner = slack.client.users_info(user=owner_link.integration_id).get("user") or {}
    except Exception:
        logger.exception("slack_task_reference_owner_lookup_failed", task_id=str(task.id))
        cache[owner_link.integration_id] = False
        return False
    cache[owner_link.integration_id] = bool(
        not owner.get("deleted") and not owner.get("is_restricted") and not owner.get("is_ultra_restricted")
    )
    return cache[owner_link.integration_id]


def _attach_public_slack_thread_reference(
    *,
    slack: SlackIntegration,
    integration: WorkspaceIntegration,
    task: TaskSlackUnfurlDTO,
    event: dict,
    shared_by_slack_user_id: str,
    public_channel_cache: dict[str, bool],
    owner_access_cache: dict[str, bool],
) -> None:
    if event.get("source") != "conversations_history":
        return
    channel = event.get("channel")
    message_ts = event.get("message_ts")
    if not isinstance(channel, str) or not isinstance(message_ts, str):
        return
    thread_ts = event.get("thread_ts")
    if not isinstance(thread_ts, str):
        thread_ts = message_ts
    if tasks_facade.has_slack_thread_reference(
        task_id=task.id,
        team_id=integration.team_id,
        slack_workspace_id=integration.integration_id,
        channel=channel,
        thread_ts=thread_ts,
    ):
        return
    if not _is_normal_public_channel(slack, channel, public_channel_cache):
        return
    if not _task_owner_can_view_public_slack_channel(slack, integration, task, owner_access_cache):
        return
    tasks_facade.attach_slack_thread_reference(
        task_id=task.id,
        team_id=integration.team_id,
        slack_workspace_id=integration.integration_id,
        channel=channel,
        thread_ts=thread_ts,
        shared_by_slack_user_id=shared_by_slack_user_id,
    )


@frozen
class _UnfurlContext:
    slack: SlackIntegration
    integration: WorkspaceIntegration
    team: Team
    user: User
    uac: UserAccessControl
    event: dict
    public_channel_cache: dict[str, bool] = dataclasses.field(default_factory=dict)
    owner_access_cache: dict[str, bool] = dataclasses.field(default_factory=dict)


def _count(value: int, noun: str) -> str:
    return f"{value:,} {noun}{'' if value == 1 else 's'}"


def _humanize(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def _bar(fraction: float) -> str:
    filled = round(min(max(fraction, 0.0), 1.0) * _CHART_WIDTH)
    return "█" * filled + "░" * (_CHART_WIDTH - filled)


def _chart_label(value: object, max_len: int = _CHART_LABEL_CHARS) -> str:
    return _truncate(str(value or "").replace("`", "'"), max_len)


def _capped_lines(lines: list[str]) -> list[str]:
    if len(lines) <= _MAX_CHART_LINES:
        return lines
    kept = _MAX_CHART_LINES - 1
    return [*lines[:kept], f"+ {len(lines) - kept} more"]


@frozen
class _ChartRow:
    label: str
    bar: str
    value: str


def _chart_rows(rows: list[_ChartRow]) -> str | None:
    if not rows:
        return None
    width = max(len(row.label) for row in rows)
    lines = [f"{row.label.ljust(width)}  {row.bar}  {row.value}".rstrip() for row in rows]
    return "\n".join(_capped_lines(lines))


def _tile_grid(names: list[str]) -> str | None:
    if not names:
        return None
    width = _CHART_WIDTH + 2
    cells = [f"▪ {_chart_label(name, width)}" for name in names[:_MAX_GRID_TILES]]
    rows = [cells[index : index + 2] for index in range(0, len(cells), 2)]
    lines = ["   ".join(cell.ljust(width + 2) for cell in row).rstrip() for row in rows]
    if len(names) > _MAX_GRID_TILES:
        lines.append(f"+ {len(names) - _MAX_GRID_TILES} more")
    return "\n".join(lines)


def _question_list(questions: object) -> str | None:
    if not isinstance(questions, list):
        return None
    texts = [str(question.get("question") or "").strip() for question in questions if isinstance(question, dict)]
    lines = [f"{index}. {_truncate(text, 60)}" for index, text in enumerate(texts, 1)]
    return "\n".join(_capped_lines(lines)) or None


def _by(user: User | None) -> tuple[str, ...]:
    return (f"By {user.first_name}",) if user and user.first_name else ()


def _user(user_id: int | None) -> User | None:
    return User.objects.filter(id=user_id).only("first_name").first() if user_id else None


def _date_range(query: object) -> str | None:
    source = query.get("source") if isinstance(query, dict) else None
    date_range = source.get("dateRange") if isinstance(source, dict) else None
    date_from = date_range.get("date_from") if isinstance(date_range, dict) else None
    if not isinstance(date_from, str):
        return None
    if date_from in _NAMED_DATE_RANGES:
        return _NAMED_DATE_RANGES[date_from]
    match = re.fullmatch(r"-(\d+)([hdwmy])", date_from)
    if not match:
        return None
    amount, unit = int(match[1]), _DATE_RANGE_UNITS[match[2]]
    return f"Last {unit}" if amount == 1 else f"Last {_count(amount, unit)}"


def _variant_row(key: object, rollout_percentage: float) -> _ChartRow:
    return _ChartRow(label=_chart_label(key), bar=_bar(rollout_percentage / 100), value=f"{rollout_percentage}%")


def _flag_variants(flag: FeatureFlag) -> list[dict]:
    try:
        return flag.variants
    except ConfigFormatError:
        return []


def _insight_card(ctx: _UnfurlContext, ref: str, url: str) -> _UnfurlCard | _SkipReason:
    insight = Insight.objects.filter(team_id=ctx.team.pk, short_id=ref).first()
    if not insight:
        return "not_found"
    level = ctx.uac.get_user_access_level(insight)
    if not level or not access_level_satisfied_for_resource("insight", level, "viewer"):
        return "no_access"
    # A link copied from the insight editor carries unsaved edits in `#q`, such as another date
    # range or hidden series. The person who opens the link sees these edits, so the card shows them too.
    edited_query = adhoc_insight_query(url)
    if edited_query == insight.query:
        edited_query = None
    return _UnfurlCard(
        label=_insight_resource_label(insight),
        title=insight.name or insight.derived_name or "Untitled",
        details=(*filter(None, [_date_range(edited_query or insight.query)]), *_by(insight.created_by)),
        body=insight.description,
        timestamp=insight.last_modified_at,
        chart_insight_id=insight.id,
        chart_edited_query=edited_query,
    )


def _adhoc_insight_card(ctx: _UnfurlContext, ref: str, url: str) -> _UnfurlCard | _SkipReason:
    query = adhoc_insight_query(url)
    if query is None:
        return "not_found"
    # The card shows only with its chart, and the chart image opens without a PostHog login.
    if not ctx.team.organization.allow_publicly_shared_resources:
        return "public_sharing_disabled"
    # Rendering an ad hoc query runs it, so it needs the same access as running it directly.
    if not ctx.uac.check_access_level_for_resource("query", "viewer"):
        return "no_access"
    return _UnfurlCard(
        label=_query_resource_label(query) or "Insight",
        title="Unsaved insight",
        details=tuple(filter(None, [_date_range(query)])),
        chart_query=query,
    )


def _dashboard_card(ctx: _UnfurlContext, ref: str, url: str) -> _UnfurlCard | _SkipReason:
    dashboard = Dashboard.objects.filter(pk=ref, team_id=ctx.team.pk).first() if ref.isdigit() else None
    if not dashboard:
        return "not_found"
    level = ctx.uac.get_user_access_level(dashboard)
    if not level or not access_level_satisfied_for_resource("dashboard", level, "viewer"):
        return "no_access"
    tiles = (
        DashboardTile.objects.filter(dashboard=dashboard, insight__isnull=False, insight__deleted=False)
        .exclude(deleted=True)
        .select_related("insight")
        .order_by("id")
    )
    insights = [tile.insight for tile in tiles if tile.insight]
    ctx.uac.preload_object_access_controls(cast(list, insights))
    names = [
        insight.name or insight.derived_name or "Untitled"
        for insight in insights
        if ctx.uac.check_access_level_for_object(insight, required_level="viewer")
    ]
    return _UnfurlCard(
        label="Dashboard",
        title=dashboard.name or "Untitled",
        details=(_count(len(names), "insight"), *_by(dashboard.created_by)),
        chart=_tile_grid(names),
        body=dashboard.description,
    )


def _ticket_card(ctx: _UnfurlContext, ref: str, url: str) -> _UnfurlCard | _SkipReason:
    # Ticket numbers are per-project sequential, so the same number exists in every project.
    # Unlike insights/dashboards (globally-unique ids, safe to resolve within the connected
    # project), a link that names a different project must not resolve to our project's ticket
    # of the same number — refuse rather than show the wrong ticket.
    url_team_id = _url_team_id(url)
    if url_team_id is not None and url_team_id != ctx.team.pk:
        return "other_project"
    ticket = _find_ticket(ctx.team.pk, ref)
    if not ticket:
        return "not_found"
    if not ctx.uac.check_access_level_for_object(ticket, required_level="viewer"):
        return "no_access"
    return _UnfurlCard(
        label="Support ticket",
        title=f"Ticket #{ticket.ticket_number}",
        status=ticket.get_status_display(),
        details=(
            f"Requested by {_ticket_requester(ctx.team, ticket)}",
            *((f"{ticket.get_priority_display()} priority",) if ticket.priority else ()),
        ),
        body=_ticket_opening_message(ctx.team.pk, ticket.id),
        timestamp=ticket.created_at,
        timestamp_label="Opened",
    )


def _may_read_tasks(uac: UserAccessControl) -> bool:
    return uac.check_access_level_for_resource("task", "viewer")


def _task_card(ctx: _UnfurlContext, ref: str, url: str) -> _UnfurlCard | _SkipReason:
    url_team_id = _url_team_id(url)
    if url_team_id is not None and url_team_id != ctx.team.pk:
        return "other_project"
    if not _may_read_tasks(ctx.uac):
        return "no_access"
    task = tasks_facade.get_task_for_slack_unfurl(ref, ctx.team.pk, ctx.user.id) if _uuid(ref) else None
    if task is None:
        return "not_found_or_no_access"
    try:
        _attach_public_slack_thread_reference(
            slack=ctx.slack,
            integration=ctx.integration,
            task=task,
            event=ctx.event,
            shared_by_slack_user_id=ctx.event["user"],
            public_channel_cache=ctx.public_channel_cache,
            owner_access_cache=ctx.owner_access_cache,
        )
    except Exception:
        logger.exception("slack_task_reference_attach_failed", task_id=str(task.id), team_id=ctx.team.pk)
    pr_url = tasks_facade.get_latest_pr_url_by_task([task.id]).get(str(task.id))
    dto = next(iter(tasks_facade.get_tasks_by_ids([task.id], [ctx.team.pk])), None)
    return _UnfurlCard(
        label="Task",
        title=task.title,
        status=task.latest_run_status,
        details=(*((dto.repository,) if dto and dto.repository else ()), *_by(_user(task.created_by_id))),
        button=_CardButton(label="View pull request", url=pr_url) if pr_url else None,
        timestamp=dto.updated_at if dto else None,
    )


def _file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    value = size / 1024
    for unit in ("KB", "MB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _task_artifact_card(ctx: _UnfurlContext, ref: str, url: str) -> _UnfurlCard | _SkipReason:
    artifact_ref = _task_artifact_ref(url)
    if artifact_ref is None:
        return "not_found"
    if artifact_ref.project_id is not None and artifact_ref.project_id != ctx.team.pk:
        return "other_project"
    if not _may_read_tasks(ctx.uac):
        return "no_access"
    artifact = tasks_facade.get_task_artifact_for_slack_unfurl(
        task_id=artifact_ref.task_id,
        team_id=ctx.team.pk,
        user_id=ctx.user.id,
        run_id=artifact_ref.run_id,
        artifact_id=artifact_ref.artifact_id,
        name=artifact_ref.name,
    )
    if artifact is None:
        return "not_found_or_no_access"
    origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    artifacts_tab = urlencode(
        {"task": artifact.task_id, "artifact": artifact.name, "artifact_version": artifact.artifact_id}
    )
    size = _file_size(artifact.size) if artifact.size is not None else None
    return _UnfurlCard(
        label="Task artifact",
        title=artifact.name,
        details=(*filter(None, [size]), f"Task: {artifact.task_title}"),
        timestamp=artifact.uploaded_at,
        timestamp_label="Uploaded",
        button=_CardButton(label="Download", url=f"{origin}{artifact.download_path}"),
        open_url=f"{origin}/project/{ctx.team.pk}/ai?{artifacts_tab}",
        artifact_image=(
            artifact.content_type in _SLACK_IMAGE_CONTENT_TYPES
            and artifact.size is not None
            and artifact.size <= _MAX_ARTIFACT_IMAGE_BYTES
        ),
    )


def _canvas_card(ctx: _UnfurlContext, ref: str, url: str) -> _UnfurlCard | _SkipReason:
    summary = canvas_access.live_canvas_summary(team_id=ctx.team.pk, canvas_id=ref) if _uuid(ref) else None
    if summary is None:
        return "not_found"
    if not canvas_access.canvas_is_visible(team_id=ctx.team.pk, canvas_id=ref, user_id=ctx.user.id):
        return "no_access"
    owner = _user(canvas_access.canvas_owner_id(team_id=ctx.team.pk, canvas_id=ref))
    return _UnfurlCard(label="Canvas", title=summary.name, details=(f"Space: {summary.channel_name}", *_by(owner)))


def _notebook_card(ctx: _UnfurlContext, ref: str, url: str) -> _UnfurlCard | _SkipReason:
    notebook = (
        Notebook.objects.filter(team_id=ctx.team.pk, short_id=ref, deleted=False)
        .exclude(visibility=Notebook.Visibility.INTERNAL)
        .defer("content", "text_content")
        .annotate(excerpt=Substr("text_content", 1, _MAX_BODY_CHARS + 1))
        .first()
    )
    if not notebook:
        return "not_found"
    if not ctx.uac.check_access_level_for_object(notebook, required_level="viewer"):
        return "no_access"
    return _UnfurlCard(
        label="Notebook",
        title=notebook.title or "Untitled",
        details=_by(notebook.created_by),
        body=notebook.excerpt,
        timestamp=notebook.last_modified_at,
    )


def _flag_chart(conditions: list[dict], variants: list[dict]) -> str | None:
    rows = [_variant_row(variant["key"], variant["rollout_percentage"]) for variant in variants]
    if len(conditions) == 1 and not conditions[0].get("properties"):
        rollout = condition_rollout_percentage(conditions[0])
        rows.insert(0, _ChartRow(label="Rollout", bar=_bar(rollout / 100), value=f"{rollout}% of users"))
    return _chart_rows(rows)


def _flag_card(ctx: _UnfurlContext, ref: str, url: str) -> _UnfurlCard | _SkipReason:
    flag = FeatureFlag.objects.filter(team_id=ctx.team.pk, pk=ref, deleted=False).first()
    if not flag:
        return "not_found"
    if not ctx.uac.check_access_level_for_object(flag, required_level="viewer"):
        return "no_access"
    try:
        conditions: list[dict] | None = flag.conditions
    except ConfigFormatError:
        conditions = None
    condition_count = _count(len(conditions), "release condition") if conditions is not None else None
    return _UnfurlCard(
        label="Feature flag",
        title=flag.key,
        status="Active" if flag.active else "Disabled",
        details=(*filter(None, [condition_count]), *_by(flag.created_by)),
        chart=_flag_chart(conditions or [], _flag_variants(flag)),
        body=flag.name,
        timestamp=flag.updated_at,
    )


def _experiment_card(ctx: _UnfurlContext, ref: str, url: str) -> _UnfurlCard | _SkipReason:
    experiment = (
        experiments_slack.get_experiment_unfurl(team_id=ctx.team.pk, experiment_id=int(ref)) if ref.isdigit() else None
    )
    if not experiment:
        return "not_found"
    # The experiment can sit on the legacy parent of the sharer's team. Access rules resolve against the sharer's team,
    # and the check raises for a reference to another team, so the reference names the sharer's team.
    access_ref = ObjectAccessRef(
        resource="experiment", id=str(experiment.id), team_id=ctx.team.pk, created_by_id=experiment.created_by_id
    )
    if not ctx.uac.check_access_level_for_ref(access_ref, "viewer"):
        return "no_access"
    details: list[str] = []
    if experiment.start_date:
        days = ((experiment.end_date or timezone.now()) - experiment.start_date).days + 1
        details.append(f"Ran {_count(days, 'day')}" if experiment.end_date else f"Day {days}")
    stats = _stored_primary_result(team_id=ctx.team.pk, experiment_id=experiment.id)
    metric = stats.metric_name if stats else experiment.primary_metric_name
    if metric:
        details.append(f"Metric: {metric}")
    if stats:
        details.append(f"Split {'/'.join(str(variant.rollout_percentage) for variant in experiment.variants)}")
    variant_rows = [_variant_row(variant.key, variant.rollout_percentage) for variant in experiment.variants]
    return _UnfurlCard(
        label="Experiment",
        title=experiment.name,
        status=_humanize(experiment.status),
        details=tuple(details),
        chart=_experiment_chart(stats) if stats else _chart_rows(variant_rows),
        body="\n\n".join(
            part for part in (_experiment_verdict(stats) if stats else None, experiment.description) if part
        ),
        timestamp=experiment.updated_at,
    )


def _stored_primary_result(*, team_id: int, experiment_id: int) -> StoredPrimaryResult | None:
    try:
        stats = experiments_facade.get_stored_primary_result(team_id=team_id, experiment_id=experiment_id)
    except Exception:
        logger.exception("slack_app_unfurl_experiment_results_failed", experiment_id=experiment_id)
        return None
    if (
        stats is None
        or stats.metric_type not in ("funnel", "mean")
        or stats.baseline.mean is None
        or not stats.variants
    ):
        return None
    return stats


def _variant_delta(stats: StoredPrimaryResult, variant: StoredArmResult) -> float | None:
    if variant.change is not None:
        return variant.change
    if variant.mean is None or stats.baseline.mean is None or stats.baseline.mean <= 0:
        return None
    return variant.mean / stats.baseline.mean - 1


def _experiment_verdict(stats: StoredPrimaryResult) -> str:
    control = stats.baseline.key
    if all(variant.change is None for variant in stats.variants):
        exposed = stats.baseline.number_of_samples + sum(variant.number_of_samples for variant in stats.variants)
        return f"⏳ *Too early to call.* {exposed:,} exposed so far."
    direction = -1 if stats.goal == "decrease" else 1
    ranked = sorted(
        ((variant, delta) for variant in stats.variants if (delta := _variant_delta(stats, variant)) is not None),
        key=lambda pair: pair[1] * direction,
        reverse=True,
    )
    significant = [(variant, delta) for variant, delta in ranked if variant.significant]
    if significant and significant[0][1] * direction > 0:
        return f"🏆 *Winner so far: {significant[0][0].key}.* {significant[0][1]:+.1%} vs {control}."
    if significant:
        return f"🔻 *Losing: {significant[-1][0].key}.* {significant[-1][1]:+.1%} vs {control}."
    if ranked and ranked[0][1] * direction > 0:
        return f"⚖️ *No clear winner yet.* {ranked[0][0].key} leads at {ranked[0][1]:+.1%} vs {control}, but it is not significant."
    return f"⚖️ *No clear winner yet.* No variant beats {control}."


def _experiment_chart(stats: StoredPrimaryResult) -> str | None:
    arms = [stats.baseline, *stats.variants]
    means = [arm.mean for arm in arms if arm.mean is not None]
    show_bars = all(mean >= 0 for mean in means)
    top = max(means, default=0.0)
    rows = []
    for arm in arms:
        if arm.mean is None:
            value = "—"
        else:
            value = f"{arm.mean:.1%}" if stats.proportion else f"{arm.mean:,.2f}"
        if arm is not stats.baseline and (delta := _variant_delta(stats, arm)) is not None:
            value += f"  {delta:+.1%}{' ✓' if arm.significant else ''}"
        bar = _bar((arm.mean or 0.0) / top if top else 0.0) if show_bars else ""
        rows.append(_ChartRow(label=_chart_label(arm.key), bar=bar, value=value))
    return _chart_rows(rows)


def _survey_status(survey: Survey) -> str:
    if survey.archived:
        return "Archived"
    if survey.end_date:
        return "Completed"
    if survey.start_date and survey.start_date > timezone.now():
        return "Scheduled"
    return "Running" if survey.start_date else "Draft"


def _survey_card(ctx: _UnfurlContext, ref: str, url: str) -> _UnfurlCard | _SkipReason:
    survey = Survey.objects.filter(team_id=ctx.team.pk, pk=ref).first() if _uuid(ref) else None
    if not survey:
        return "not_found"
    if not ctx.uac.check_access_level_for_object(survey, required_level="viewer"):
        return "no_access"
    return _UnfurlCard(
        label="Survey",
        title=survey.name,
        status=_survey_status(survey),
        details=(_count(len(survey.questions or []), "question"), *_by(survey.created_by)),
        chart=_question_list(survey.questions),
        body=survey.description,
        timestamp=survey.updated_at,
    )


def _cohort_card(ctx: _UnfurlContext, ref: str, url: str) -> _UnfurlCard | _SkipReason:
    cohort = Cohort.objects.filter(team_id=ctx.team.pk, pk=ref, deleted=False).first() if ref.isdigit() else None
    if not cohort:
        return "not_found"
    if not ctx.uac.check_access_level_for_object(cohort, required_level="viewer"):
        return "no_access"
    return _UnfurlCard(
        label="Static cohort" if cohort.is_static else "Cohort",
        title=cohort.name or "Untitled",
        details=(*((_count(cohort.count, "person"),) if cohort.count is not None else ()), *_by(cohort.created_by)),
        body=cohort.description,
        timestamp=cohort.last_calculation,
        timestamp_label="Calculated",
    )


def _error_card(ctx: _UnfurlContext, ref: str, url: str) -> _UnfurlCard | _SkipReason:
    issue_id = _uuid(ref)
    if issue_id is None:
        return "not_found"
    try:
        issue = error_tracking_facade.get_issue(issue_id, ctx.team.pk)
    except error_tracking_facade.IssueNotFoundError:
        return "not_found"
    access = ctx.uac.access_level_for_resource("error_tracking")
    if not access or not access_level_satisfied_for_resource("error_tracking", access.access_level, "viewer"):
        return "no_access"
    return _UnfurlCard(
        label="Error issue",
        title=issue.name or "Untitled issue",
        status=_humanize(issue.status),
        details=(f"{issue.severity.capitalize()} severity",) if issue.severity else (),
        body=issue.description,
        timestamp=issue.first_seen,
        timestamp_label="First seen",
    )


def _report_card(ctx: _UnfurlContext, ref: str, url: str) -> _UnfurlCard | _SkipReason:
    report = (
        SignalReport.objects.filter(team_id=ctx.team.pk, pk=ref).exclude(status=SignalReport.Status.DELETED).first()
        if _uuid(ref)
        else None
    )
    if not report:
        return "not_found"
    if not may_read_reports(user=ctx.user, team=ctx.team):
        return "no_access"
    return _UnfurlCard(
        label="Inbox report",
        title=report.title or "Untitled report",
        status=_humanize(report.status),
        details=(_count(report.signal_count, "signal"),),
        timestamp=report.updated_at,
    )


_CARD_BUILDERS: dict[str, Callable[[_UnfurlContext, str, str], _UnfurlCard | _SkipReason]] = {
    "insight": _insight_card,
    ADHOC_INSIGHT_KIND: _adhoc_insight_card,
    "dashboard": _dashboard_card,
    "ticket": _ticket_card,
    "task": _task_card,
    TASK_ARTIFACT_KIND: _task_artifact_card,
    "canvas": _canvas_card,
    "notebook": _notebook_card,
    "flag": _flag_card,
    "experiment": _experiment_card,
    "survey": _survey_card,
    "cohort": _cohort_card,
    "error": _error_card,
    "report": _report_card,
}


def _unfurls(cards: dict[str, tuple[str, _UnfurlCard]], *, compact: bool, invite: dict | None) -> dict[str, dict]:
    unfurls = {
        url: {"blocks": _card_blocks(card, kind=kind, url=url, compact=compact)} for url, (kind, card) in cards.items()
    }
    if invite:
        next(iter(unfurls.values()))["blocks"].append(invite)
    return unfurls


def _post_unfurls(slack: SlackIntegration, event: dict, unfurls: dict[str, dict]) -> str | None:
    try:
        slack.client.chat_unfurl(
            **chat_unfurl_kwargs(
                channel=event["channel"],
                ts=event["message_ts"],
                unfurls=unfurls,
                unfurl_id=event.get("unfurl_id"),
                source=event.get("source"),
            )
        )
    except SlackApiError as e:
        error = (e.response.get("error") if e.response is not None else None) or "slack_api_error"
        logger.warning("slack_link_unfurl_chat_unfurl_failed", channel=event["channel"], error=error)
        return error
    except Exception:
        logger.exception("slack_link_unfurl_chat_unfurl_failed", channel=event["channel"])
        return "unknown"
    return None


def start_unfurl_charts(
    *,
    integration: WorkspaceIntegration,
    user: User,
    event: dict,
    unfurls: dict[str, dict],
    charts: list[SlackUnfurlChartRequest],
) -> None:
    """Start the workflow that adds chart images to the posted cards. Best effort: a failure keeps the text cards.

    The image url opens without a PostHog login, so an organization that turns off public
    sharing gets no charts.
    """
    if not integration.team.organization.allow_publicly_shared_resources:
        return
    channel = event["channel"]
    message_ts = event["message_ts"]
    inputs = SlackAppUnfurlChartsWorkflowInputs(
        team_id=integration.team_id,
        integration_id=integration.id,
        user_id=user.pk,
        slack_user_id=event["user"],
        channel=channel,
        message_ts=message_ts,
        unfurl_id=event.get("unfurl_id"),
        source=event.get("source"),
        unfurls=unfurls,
        charts=charts,
        export_task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
    )
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                SlackAppUnfurlChartsWorkflow.run,
                inputs,
                id=f"slack-app-unfurl-charts-{integration.integration_id}:{channel}:{message_ts}",
                task_queue=settings.TASKS_TASK_QUEUE,
                execution_timeout=SLACK_APP_UNFURL_CHARTS_WORKFLOW_TIMEOUT,
            )
        )
    except WorkflowAlreadyStartedError:
        # Slack sent the event again while the first run is still rendering.
        pass
    except Exception:
        logger.warning("slack_app_unfurl_charts_dispatch_failed", team_id=integration.team_id, exc_info=True)


def _queue_unfurl_charts(
    *,
    integration: WorkspaceIntegration,
    user: User,
    event: dict,
    unfurls: dict[str, dict],
    charts: list[SlackUnfurlChartRequest],
) -> bool:
    """Queue ``start_unfurl_charts`` on Celery. The flag check and the Temporal start make network
    calls, and the webhook must ack within Slack's three-second budget."""
    # noqa reason: the task module imports api, which imports this module at load time.
    from products.slack_app.backend.tasks import start_slack_unfurl_charts  # noqa: PLC0415

    try:
        start_slack_unfurl_charts.delay(
            team_id=integration.team_id,
            integration_id=integration.id,
            user_id=user.pk,
            event=event,
            unfurls=unfurls,
            charts=[dataclasses.asdict(chart) for chart in charts],
        )
    except Exception:
        logger.warning("slack_app_unfurl_charts_queue_failed", team_id=integration.team_id, exc_info=True)
        return False
    return True


def _queue_unfurl_artifact_image(
    *, integration: WorkspaceIntegration, user: User, event: dict, unfurls: dict[str, dict], url: str, title: str
) -> bool:
    """Reading and storing the file is too slow for the webhook's ack budget, so it runs on Celery."""
    # noqa reason: the task module imports api, which imports this module at load time.
    from products.slack_app.backend.tasks import add_slack_unfurl_artifact_image  # noqa: PLC0415

    try:
        add_slack_unfurl_artifact_image.delay(
            team_id=integration.team_id,
            integration_id=integration.id,
            user_id=user.pk,
            event=event,
            unfurls=unfurls,
            url=url,
            title=title,
        )
    except Exception:
        logger.warning("slack_app_unfurl_artifact_image_queue_failed", team_id=integration.team_id, exc_info=True)
        return False
    return True


_ImageFailure = Literal["public_sharing_disabled", "no_access", "unavailable", "not_an_image", "unfurl_failed"]


@frozen
class _ImageLink:
    url: str | None = None
    failure: _ImageFailure | None = None


def _artifact_image_link(*, integration: WorkspaceIntegration, user: User, url: str, title: str) -> _ImageLink:
    # The link opens without a PostHog login, so it follows the public sharing setting like chart images do.
    team = integration.team
    if not team.organization.allow_publicly_shared_resources:
        return _ImageLink(failure="public_sharing_disabled")
    # Access can change while the job waits in the queue, and the link it publishes needs no login.
    if not has_project_access(user, team) or not _may_read_tasks(UserAccessControl(user, team=team)):
        return _ImageLink(failure="no_access")
    artifact_ref = _task_artifact_ref(url)
    content = (
        tasks_facade.read_task_artifact_for_slack_unfurl(
            task_id=artifact_ref.task_id,
            team_id=integration.team_id,
            user_id=user.pk,
            max_bytes=_MAX_ARTIFACT_IMAGE_BYTES,
            run_id=artifact_ref.run_id,
            artifact_id=artifact_ref.artifact_id,
            name=artifact_ref.name,
        )
        if artifact_ref
        else None
    )
    if content is None:
        return _ImageLink(failure="unavailable")
    image_url = exports_facade.create_png_delivery_url(
        team_id=integration.team_id,
        created_by_id=user.pk,
        content=content,
        filename=title,
        url_ttl=UNFURL_IMAGE_URL_TTL,
        asset_ttl=UNFURL_IMAGE_ASSET_TTL,
    )
    if image_url is None:
        return _ImageLink(failure="not_an_image")
    return _ImageLink(url=slack_fetchable_image_url(image_url))


def add_artifact_image_to_unfurl(
    *, integration: WorkspaceIntegration, user: User, event: dict, unfurls: dict[str, dict], url: str, title: str
) -> None:
    """Post a task artifact card again with its image. Best effort: a failure keeps the text card."""
    link = _artifact_image_link(integration=integration, user=user, url=url, title=title)
    failure = link.failure
    error: str | None = None
    if link.url is not None:
        error = _post_unfurls(
            SlackIntegration(integration), event, with_chart_images(unfurls, {url: link.url}, {url: title})
        )
        failure = "unfurl_failed" if error else None
    logger.info(
        "slack_app_unfurl_artifact_image_result",
        team_id=integration.team_id,
        channel=event.get("channel"),
        failure=failure,
        error=error,
    )
    capture_slack_event(
        integration,
        "slack app link unfurl artifact image",
        slack_user_id=event["user"],
        posthog_user=user,
        shown=failure is None,
        failure=failure,
        error=error,
    )


def _bot_reply_actor(integration: WorkspaceIntegration, event: dict) -> str | None:
    """The Slack user steering the run in this thread, when that run was told to share chart links.

    Slack credits a message our app posts to our bot user, and some bot-posted messages to the
    placeholder author. Neither resolves to a PostHog user, so a thread whose run shares links is
    the signal that such a message is our reply, written for that person with their PostHog
    access. The run state holds the decision, so no flag call here."""
    if not event.get("thread_ts"):
        return None
    actors = (
        SlackThreadTaskMapping.objects.filter(
            integration_id=integration.id,
            channel=event["channel"],
            thread_ts=event["thread_ts"],
            task_run__state__slack_chart_links=True,
        )
        .values_list(
            "task_run__state__slack_actor_slack_user_id", "latest_actor_slack_user_id", "mentioning_slack_user_id"
        )
        .first()
    )
    return next((actor for actor in actors or () if actor), None)


def handle_posthog_link_unfurl(event: dict, integration: WorkspaceIntegration) -> None:
    """
    Unfurl supported PostHog resource links with metadata.

    Scope is always the Slack-connected project (`integration.team`); `resolve_slack_user` enforces
    that the sharer can access it. Each resource adds its own access check. Ticket and task links
    naming a different project are also refused because ticket numbers are per-project and could
    otherwise resolve to the wrong ticket.
    """
    slack = SlackIntegration(integration)
    channel = event.get("channel")
    message_ts = event.get("message_ts")
    slack_user_id = event.get("user")
    links = event.get("links") or []

    if not channel or not message_ts or not slack_user_id or not links:
        logger.info("slack_link_unfurl_skip_missing_fields", has_channel=bool(channel), has_ts=bool(message_ts))
        return

    # Imported here to avoid circular import with api (api imports this module at load time).
    from products.slack_app.backend.api import SLACK_PLACEHOLDER_USER_ID, resolve_slack_user

    bot_authors = {SLACK_PLACEHOLDER_USER_ID, get_cached_bot_user_id(slack, integration)}
    shared_by_person = slack_user_id not in bot_authors
    bot_reply_actor = None if shared_by_person else _bot_reply_actor(integration, event)
    if bot_reply_actor:
        slack_user_id = bot_reply_actor
        # Everything downstream, the chart workflow included, reads the sharer from the event.
        event = {**event, "user": bot_reply_actor}

    user_context = resolve_slack_user(
        slack,
        integration,
        slack_user_id,
        channel,
        message_ts,
        post_feedback=False,
    )
    if not user_context:
        logger.info(
            "slack_app_link_unfurl_user_unresolved",
            team_id=integration.team_id,
            integration_id=integration.id,
            slack_user_id=slack_user_id,
        )
        return

    user = user_context.user
    team = integration.team
    ctx = _UnfurlContext(
        slack=slack,
        integration=integration,
        team=team,
        user=user,
        uac=UserAccessControl(user, team=team),
        event=event,
    )

    cards: dict[str, tuple[str, _UnfurlCard]] = {}
    # Every resource we recognized but chose not to unfurl, so a report of "no unfurl appeared"
    # can be answered from logs instead of by re-deriving the path by hand.
    skipped: list[dict[str, str]] = []

    for link_obj in links:
        raw_url = link_obj.get("url")
        if not raw_url:
            continue

        ref = parse_posthog_resource_link(raw_url)
        if not ref:
            known = object_ref_for_url(raw_url)
            if known and known.kind not in _CARD_BUILDERS:
                skipped.append({"kind": known.kind, "reason": "unsupported"})
            continue

        # Resource ids repeat across regions, so a link for the other region would otherwise resolve
        # to whatever local resource carries the same id and unfurl the wrong thing. Routing sends
        # single-region messages to the region that owns them; this catches the leftover case of one
        # message carrying links for both.
        url_region = link_url_region(raw_url)
        if url_region is not None and url_region != get_instance_region():
            skipped.append({"kind": ref.kind, "ref": ref.id, "reason": "other_region"})
            continue

        card = _CARD_BUILDERS[ref.kind](ctx, ref.id, raw_url)
        if isinstance(card, str):
            skipped.append({"kind": ref.kind, "ref": ref.id, "reason": card})
            continue
        cards[raw_url] = (ref.kind, card)

    # A card shows a chart only when it is the only link. An ad hoc card has no card without its
    # chart, because the flag check is a network call this webhook cannot afford before it acks.
    adhoc = {url: entry for url, entry in cards.items() if entry[1].chart_query is not None}
    if adhoc and len(cards) > 1:
        skipped.extend({"kind": kind, "ref": "new", "reason": "multiple_links"} for kind, _ in adhoc.values())
        cards = {url: entry for url, entry in cards.items() if url not in adhoc}
        adhoc = {}

    logger.info(
        "slack_app_link_unfurl_result",
        team_id=team.pk,
        integration_id=integration.id,
        channel=channel,
        unfurled=len(cards) - len(adhoc),
        deferred=len(adhoc),
        skipped=skipped,
    )

    if adhoc:
        url, (_, card) = next(iter(adhoc.items()))
        _queue_unfurl_charts(
            integration=integration,
            user=user,
            event=event,
            unfurls=_unfurls(adhoc, compact=False, invite=None),
            charts=[SlackUnfurlChartRequest(url=url, query=card.chart_query, title=card.title)],
        )
        return

    if not cards:
        return

    invite_kind, _ = next(iter(cards.values()))
    invite = _build_unfurl_invite(integration, invite_kind, channel)
    kinds = sorted({kind for kind, _ in cards.values()})
    for compact in (True,) if len(cards) > 1 else (False, True):
        unfurls = _unfurls(cards, compact=compact, invite=invite)
        error = _post_unfurls(slack, event, unfurls)
        if error is None:
            break
        capture_slack_event(
            integration,
            "slack app link unfurl failed",
            slack_user_id=slack_user_id,
            posthog_user=user,
            kinds=kinds,
            compact=compact,
            error=error,
            bot_reply=bot_reply_actor is not None,
        )
        if error not in _REJECTED_PAYLOAD_ERRORS:
            return
    else:
        return

    chart_requests = [
        SlackUnfurlChartRequest(url=url, query=card.chart_edited_query, title=card.title)
        if card.chart_edited_query is not None
        else SlackUnfurlChartRequest(url=url, insight_id=card.chart_insight_id, title=card.title)
        for url, (_, card) in cards.items()
        if card.chart_insight_id is not None and not compact
    ]
    charts_queued = bool(chart_requests) and _queue_unfurl_charts(
        integration=integration,
        user=user,
        event=event,
        unfurls=unfurls,
        charts=chart_requests,
    )
    # A card is full size, and can carry an image, only when it is the only link.
    first_url, (_, first_card) = next(iter(cards.items()))
    artifact_image_queued = (
        not compact
        and first_card.artifact_image
        and _queue_unfurl_artifact_image(
            integration=integration, user=user, event=event, unfurls=unfurls, url=first_url, title=first_card.title
        )
    )
    if shared_by_person:
        record_feature_used(integration.integration_id, slack_user_id, SlackFeature.INSIGHT_UNFURL)
    capture_slack_event(
        integration,
        "slack app link unfurled",
        slack_user_id=slack_user_id,
        posthog_user=user,
        kinds=kinds,
        unfurled_count=len(unfurls),
        compact=compact,
        skipped_count=len(skipped),
        followup_invite_shown=invite is not None,
        charts_queued=charts_queued,
        artifact_image_queued=artifact_image_queued,
        bot_reply=bot_reply_actor is not None,
    )
