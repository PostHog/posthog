"""Slack link unfurling for PostHog resource URLs (metadata only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from django.core.exceptions import ValidationError

import structlog

from posthog.models import Team, User
from posthog.models.comment import Comment
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user_integration import UserIntegration
from posthog.rbac.user_access_control import UserAccessControl

from products.conversations.backend.models.ticket import Ticket
from products.dashboards.backend.models.dashboard import Dashboard
from products.product_analytics.backend.models.insight import Insight
from products.slack_app.backend.services.integration_resolver import ResolutionResult, resolve_user_for_workspace
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskSlackUnfurlDTO

logger = structlog.get_logger(__name__)

ResourceKind = Literal["insight", "dashboard", "ticket", "task"]

# Kinds whose reference is only unique within a project — ticket numbers restart per project — so a
# link naming a project must resolve there or not at all.
_PROJECT_SCOPED_REFS: frozenset[ResourceKind] = frozenset({"ticket"})

_MAX_DESCRIPTION_CHARS = 2800
# Keep title + status + message under Slack's 3000-char section limit; the client shows "Show more".
_MAX_OPENING_MESSAGE_CHARS = 2000

# Query `source.kind` / top-level `kind` → short name before " insight" (sync with InsightType / query kinds).
_QUERY_KIND_TO_SHORT_NAME: dict[str, str] = {
    "TrendsQuery": "Trends",
    "FunnelsQuery": "Funnel",
    "FunnelCorrelationQuery": "Funnel correlation",
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
    return text[: max_len - 1] + "…"


def parse_posthog_resource_link(url: str) -> tuple[ResourceKind, str | int] | None:
    """
    Parse a PostHog app URL into (resource kind, reference id).

    Reference is insight short_id (str), dashboard primary key (int), or ticket ref (str — ticket
    number or UUID).

    The `/project/:id` segment is skipped here; `_url_team_id` reads it separately to pick which
    connected project a link resolves against.

    Related: `removeProjectIdIfPresent` + `urlToResource` (`router-utils.ts`, `urls.ts`); legacy paths in `get_target_queryset` (`middleware.py`).
    """
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None

    idx = 0
    if len(parts) >= 2 and parts[0] == "project":
        # Picking a project is not authorization — see handle_posthog_link_unfurl.
        idx = 2

    if len(parts) > idx and parts[idx] == "i" and len(parts) > idx + 1:
        short_id = parts[idx + 1]
        if short_id == "new":
            return None
        return ("insight", short_id)

    if len(parts) > idx and parts[idx] == "insights" and len(parts) > idx + 1:
        short_id = parts[idx + 1]
        if short_id in ("new", "options"):
            return None
        return ("insight", short_id)

    if len(parts) > idx and parts[idx] == "dashboard" and len(parts) > idx + 1:
        try:
            dashboard_id = int(parts[idx + 1])
        except ValueError:
            return None
        return ("dashboard", dashboard_id)

    if len(parts) > idx + 2 and parts[idx] == "support" and parts[idx + 1] == "tickets":
        ref = parts[idx + 2]
        if ref == "new":
            return None
        return ("ticket", ref)

    if len(parts) > idx and parts[idx] == "tasks" and len(parts) > idx + 1:
        try:
            task_id = UUID(parts[idx + 1])
        except ValueError:
            return None
        return ("task", str(task_id))

    return None


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


def _insight_resource_label(insight: Insight) -> str:
    """e.g. 'Trends insight', 'SQL insight' — from query JSON or legacy filters only (no execution)."""
    q = insight.query
    if isinstance(q, dict) and q:
        inner = _extract_query_source_kind(q)
        if inner:
            short = _QUERY_KIND_TO_SHORT_NAME.get(inner)
            if short:
                return f"{short} insight"
            if inner.endswith("Query"):
                return f"{inner[: -len('Query')]} insight"
            return f"{inner} insight"

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


def _escape_mrkdwn(text: str) -> str:
    """Escape mrkdwn control chars — ticket subjects/messages are customer-authored."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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
    return _truncate(_escape_mrkdwn((content or "").strip()), _MAX_OPENING_MESSAGE_CHARS) or None


def _unfurl_payload(*, resource_label: str, title: str, description: str | None) -> dict:
    title = title or "Untitled"
    body = f"*{title} • {resource_label}*"
    if description:
        body += "\n\n" + _truncate(description.strip(), _MAX_DESCRIPTION_CHARS)
    return {"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": body}}]}


def _ticket_unfurl_payload(*, url: str, ticket: Ticket, requester: str, opening_message: str | None) -> dict:
    """A linked title, a requester/status context line, and (optionally) the quoted opening message."""
    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"<{url}|*Support Ticket #{ticket.ticket_number}*>"}},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"*Requested by:* {requester}  •  *Status:* {ticket.get_status_display()}"}
            ],
        },
    ]
    if opening_message:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f">>> {opening_message}"}})
    return {"blocks": blocks}


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
    integration: Integration,
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
    integration: Integration,
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


def _candidates_for_link(
    kind: ResourceKind, url_team_id: int | None, candidates: list[Integration]
) -> list[Integration]:
    """The connected projects to try for one link: the one its URL names, else all of them.

    A link with no `/project/:id`, or one naming a project this workspace hasn't connected, falls
    back to every candidate — except for kinds whose reference only means something within a
    project. Picking a project is not authorization; the per-resource check still runs.
    """
    if url_team_id is None:
        return candidates
    named = [c for c in candidates if c.team_id == url_team_id]
    return named if named or kind in _PROJECT_SCOPED_REFS else candidates


@dataclass(frozen=True, kw_only=True)
class _UnfurlContext:
    """Everything constant across the links in one `link_shared` event."""

    slack: SlackIntegration
    user: User
    event: dict
    shared_by_slack_user_id: str
    access_by_team: dict[int, UserAccessControl]
    public_channel_cache: dict[str, bool] = field(default_factory=dict)
    owner_access_cache: dict[str, bool] = field(default_factory=dict)


def _unfurl_for_resource(
    ctx: _UnfurlContext, *, integration: Integration, raw_url: str, kind: ResourceKind, ref: str | int
) -> dict | None:
    """Build the unfurl payload for one link against one project, or None if it doesn't resolve there."""
    team = integration.team
    uac = ctx.access_by_team[team.pk]

    if kind == "insight":
        if not isinstance(ref, str):
            return None
        insight = Insight.objects.filter(team_id=team.pk, short_id=ref).first()
        if not insight or not uac.check_access_level_for_object(insight, required_level="viewer"):
            return None
        title = insight.name or insight.derived_name or "Untitled"
        desc = (insight.description or "").strip() or None
        return _unfurl_payload(resource_label=_insight_resource_label(insight), title=title, description=desc)

    if kind == "dashboard":
        if not isinstance(ref, int):
            return None
        dashboard = Dashboard.objects.filter(pk=ref, team_id=team.pk).first()
        if not dashboard or not uac.check_access_level_for_object(dashboard, required_level="viewer"):
            return None
        title = dashboard.name or "Untitled"
        desc = (dashboard.description or "").strip() or None
        return _unfurl_payload(resource_label="Dashboard", title=title, description=desc)

    if kind == "ticket":
        if not isinstance(ref, str):
            return None
        ticket = _find_ticket(team.pk, ref)
        if not ticket or not uac.check_access_level_for_object(ticket, required_level="viewer"):
            return None
        return _ticket_unfurl_payload(
            url=raw_url,
            ticket=ticket,
            requester=_escape_mrkdwn(_ticket_requester(team, ticket)),
            opening_message=_ticket_opening_message(team.pk, ticket.id),
        )

    if kind == "task":
        if not isinstance(ref, str):
            return None
        task = tasks_facade.get_task_for_slack_unfurl(ref, team.pk, ctx.user.id)
        if task is None:
            return None
        label = "Task" if task.latest_run_status is None else f"Task · {task.latest_run_status}"
        payload = _unfurl_payload(resource_label=label, title=_escape_mrkdwn(task.title), description=None)
        try:
            _attach_public_slack_thread_reference(
                slack=ctx.slack,
                integration=integration,
                task=task,
                event=ctx.event,
                shared_by_slack_user_id=ctx.shared_by_slack_user_id,
                public_channel_cache=ctx.public_channel_cache,
                owner_access_cache=ctx.owner_access_cache,
            )
        except Exception:
            logger.exception("slack_task_reference_attach_failed", task_id=str(task.id), team_id=team.pk)
        return payload


def handle_posthog_link_unfurl(event: dict, integrations: list[Integration]) -> None:
    """
    Unfurl supported PostHog resource links with metadata.

    ``integrations`` is every project this Slack workspace has connected. Each link resolves against
    the project its URL names, falling back to trying all of them. The sharer is resolved once for
    the workspace, which drops projects they can't reach, and each resource gets its own access
    check on top.
    """
    if not integrations:
        return

    channel = event.get("channel")
    message_ts = event.get("message_ts")
    slack_user_id = event.get("user")
    unfurl_id = event.get("unfurl_id")
    source = event.get("source")
    links = event.get("links") or []

    if not channel or not message_ts or not slack_user_id or not links:
        logger.info("slack_link_unfurl_skip_missing_fields", has_channel=bool(channel), has_ts=bool(message_ts))
        return

    # Imported here to avoid circular import with api (api imports this module at load time).
    from products.slack_app.backend.api import SLACK_PLACEHOLDER_USER_ID

    if slack_user_id == SLACK_PLACEHOLDER_USER_ID:
        # Slack couldn't attribute the message to a real user, so there is nobody to authorize as.
        return

    slack_team_id = integrations[0].integration_id
    resolution = resolve_user_for_workspace(
        workspace_result=ResolutionResult(integration=None, source="needs_picker", candidates=integrations),
        slack_team_id=slack_team_id,
        slack_user_id=slack_user_id,
    )
    if resolution.user is None or not resolution.candidates:
        return

    candidates = resolution.candidates
    # Any of the workspace's integrations carries a bot token for the same workspace, so the client
    # is interchangeable — only the project scope differs between candidates.
    ctx = _UnfurlContext(
        slack=SlackIntegration(candidates[0]),
        user=resolution.user,
        event=event,
        shared_by_slack_user_id=slack_user_id,
        access_by_team=UserAccessControl(resolution.user, team=candidates[0].team).for_team_ids(
            [c.team_id for c in candidates]
        ),
    )
    unfurls: dict[str, dict] = {}

    for link_obj in links:
        raw_url = link_obj.get("url")
        if not raw_url:
            continue

        parsed = parse_posthog_resource_link(raw_url)
        if not parsed:
            continue

        kind, ref = parsed
        url_team_id = _url_team_id(raw_url)
        link_candidates = _candidates_for_link(kind, url_team_id, candidates)
        payload: dict | None = None

        for integration in link_candidates:
            payload = _unfurl_for_resource(ctx, integration=integration, raw_url=raw_url, kind=kind, ref=ref)
            if payload is not None:
                break

        if payload is None:
            logger.info(
                "slack_link_unfurl_unresolved",
                resource_type=kind,
                resource_ref=str(ref),
                url_team_id=url_team_id,
                candidate_team_ids=[i.team_id for i in link_candidates],
            )
            continue

        unfurls[raw_url] = payload

    if not unfurls:
        return

    unfurl_kwargs: dict = {"channel": channel, "ts": message_ts, "unfurls": unfurls}
    if unfurl_id:
        unfurl_kwargs["unfurl_id"] = unfurl_id
    if source:
        unfurl_kwargs["source"] = source

    try:
        ctx.slack.client.chat_unfurl(**unfurl_kwargs)
    except Exception:
        logger.exception("slack_link_unfurl_chat_unfurl_failed", slack_team_id=slack_team_id, channel=channel)
