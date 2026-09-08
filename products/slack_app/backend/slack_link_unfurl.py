"""Slack link unfurling for PostHog resource URLs (metadata only)."""

from __future__ import annotations

from typing import Literal
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from django.core.exceptions import ValidationError

import structlog

from posthog.models import Team
from posthog.models.comment import Comment
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user_integration import UserIntegration
from posthog.utils import get_instance_region

from products.access_control.backend.facade.user_access_control import (
    UserAccessControl,
    access_level_satisfied_for_resource,
)
from products.conversations.backend.models.ticket import Ticket
from products.dashboards.backend.models.dashboard import Dashboard
from products.product_analytics.backend.facade.models import Insight
from products.slack_app.backend.services.slack_messages import UNFURL_OPT_OUT_PARAM
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskSlackUnfurlDTO

logger = structlog.get_logger(__name__)

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


def parse_posthog_resource_link(
    url: str,
) -> tuple[Literal["insight", "dashboard", "ticket", "task"], str | int] | None:
    """
    Parse a PostHog app URL into (resource kind, reference id).

    Reference is insight short_id (str), dashboard primary key (int), or ticket ref (str — ticket
    number or UUID).

    A URL carrying `?unfurl=false` is not a resource here: links we post ourselves already
    sit beside the detail a card would add, so they opt out rather than repeat it.

    If the path includes `/project/:id`, that segment is ignored — lookup is always scoped to the
    Slack-connected project and the resolved PostHog user, not to any project id in the URL.

    Related: `removeProjectIdIfPresent` + `urlToResource` (`router-utils.ts`, `urls.ts`); legacy paths in `get_target_queryset` (`middleware.py`).
    """
    parsed = urlparse(url)
    if "false" in parse_qs(parsed.query).get(UNFURL_OPT_OUT_PARAM, []):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None

    idx = 0
    if len(parts) >= 2 and parts[0] == "project":
        # Skip project/{anything} — do not use for authorization (see handle_posthog_link_unfurl).
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


def handle_posthog_link_unfurl(event: dict, integration: Integration) -> None:
    """
    Unfurl supported PostHog resource links with metadata.

    Scope is always the Slack-connected project (`integration.team`); `resolve_slack_user` enforces
    that the sharer can access it. Insights, dashboards, and tickets add a per-resource
    access-control check. Ticket links naming a different project are also refused because ticket
    numbers are per-project and could otherwise resolve to the wrong ticket.
    """
    slack = SlackIntegration(integration)
    channel = event.get("channel")
    message_ts = event.get("message_ts")
    slack_user_id = event.get("user")
    unfurl_id = event.get("unfurl_id")
    source = event.get("source")
    links = event.get("links") or []
    public_channel_cache: dict[str, bool] = {}
    owner_access_cache: dict[str, bool] = {}

    if not channel or not message_ts or not slack_user_id or not links:
        logger.info("slack_link_unfurl_skip_missing_fields", has_channel=bool(channel), has_ts=bool(message_ts))
        return

    # Imported here to avoid circular import with api (api imports this module at load time).
    from products.slack_app.backend.api import resolve_slack_user

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
    uac = UserAccessControl(user, team=team)

    unfurls: dict[str, dict] = {}
    # Every resource we recognized but chose not to unfurl, so a report of "no unfurl appeared"
    # can be answered from logs instead of by re-deriving the path by hand.
    skipped: list[dict[str, str]] = []

    for link_obj in links:
        raw_url = link_obj.get("url")
        if not raw_url:
            continue

        parsed = parse_posthog_resource_link(raw_url)
        if not parsed:
            continue

        kind, ref = parsed

        # Resource ids repeat across regions, so a link for the other region would otherwise resolve
        # to whatever local resource carries the same id and unfurl the wrong thing. Routing sends
        # single-region messages to the region that owns them; this catches the leftover case of one
        # message carrying links for both.
        url_region = link_url_region(raw_url)
        if url_region is not None and url_region != get_instance_region():
            skipped.append({"kind": kind, "ref": str(ref), "reason": "other_region"})
            continue

        if kind == "insight":
            if not isinstance(ref, str):
                continue
            insight = Insight.objects.filter(team_id=team.pk, short_id=ref).first()
            if not insight:
                skipped.append({"kind": kind, "ref": ref, "reason": "not_found"})
                continue
            level = uac.get_user_access_level(insight)
            if not level or not access_level_satisfied_for_resource("insight", level, "viewer"):
                skipped.append({"kind": kind, "ref": ref, "reason": "no_access"})
                continue
            title = insight.name or insight.derived_name or "Untitled"
            desc = (insight.description or "").strip() or None
            unfurls[raw_url] = _unfurl_payload(
                resource_label=_insight_resource_label(insight), title=title, description=desc
            )
        elif kind == "dashboard":
            if not isinstance(ref, int):
                continue
            dashboard = Dashboard.objects.filter(pk=ref, team_id=team.pk).first()
            if not dashboard:
                skipped.append({"kind": kind, "ref": str(ref), "reason": "not_found"})
                continue
            level = uac.get_user_access_level(dashboard)
            if not level or not access_level_satisfied_for_resource("dashboard", level, "viewer"):
                skipped.append({"kind": kind, "ref": str(ref), "reason": "no_access"})
                continue
            title = dashboard.name or "Untitled"
            desc = (dashboard.description or "").strip() or None
            unfurls[raw_url] = _unfurl_payload(resource_label="Dashboard", title=title, description=desc)
        elif kind == "ticket":
            if not isinstance(ref, str):
                continue
            # Ticket numbers are per-project sequential, so the same number exists in every project.
            # Unlike insights/dashboards (globally-unique ids, safe to resolve within the connected
            # project), a link that names a different project must not resolve to our project's ticket
            # of the same number — refuse rather than show the wrong ticket.
            url_team_id = _url_team_id(raw_url)
            if url_team_id is not None and url_team_id != team.pk:
                skipped.append({"kind": kind, "ref": ref, "reason": "other_project"})
                continue
            ticket = _find_ticket(team.pk, ref)
            if not ticket:
                skipped.append({"kind": kind, "ref": ref, "reason": "not_found"})
                continue
            if not uac.check_access_level_for_object(ticket, required_level="viewer"):
                skipped.append({"kind": kind, "ref": ref, "reason": "no_access"})
                continue
            unfurls[raw_url] = _ticket_unfurl_payload(
                url=raw_url,
                ticket=ticket,
                requester=_escape_mrkdwn(_ticket_requester(team, ticket)),
                opening_message=_ticket_opening_message(team.pk, ticket.id),
            )
        elif kind == "task":
            if not isinstance(ref, str):
                continue
            url_team_id = _url_team_id(raw_url)
            if url_team_id is not None and url_team_id != team.pk:
                skipped.append({"kind": kind, "ref": ref, "reason": "other_project"})
                continue
            task = tasks_facade.get_task_for_slack_unfurl(ref, team.pk, user.id)
            if task is None:
                skipped.append({"kind": kind, "ref": ref, "reason": "not_found_or_no_access"})
                continue
            label = "Task" if task.latest_run_status is None else f"Task · {task.latest_run_status}"
            unfurls[raw_url] = _unfurl_payload(resource_label=label, title=_escape_mrkdwn(task.title), description=None)
            try:
                _attach_public_slack_thread_reference(
                    slack=slack,
                    integration=integration,
                    task=task,
                    event=event,
                    shared_by_slack_user_id=slack_user_id,
                    public_channel_cache=public_channel_cache,
                    owner_access_cache=owner_access_cache,
                )
            except Exception:
                logger.exception("slack_task_reference_attach_failed", task_id=str(task.id), team_id=team.pk)

    logger.info(
        "slack_app_link_unfurl_result",
        team_id=team.pk,
        integration_id=integration.id,
        channel=channel,
        unfurled=len(unfurls),
        skipped=skipped,
    )

    if not unfurls:
        return

    unfurl_kwargs: dict = {"channel": channel, "ts": message_ts, "unfurls": unfurls}
    if unfurl_id:
        unfurl_kwargs["unfurl_id"] = unfurl_id
    if source:
        unfurl_kwargs["source"] = source

    try:
        slack.client.chat_unfurl(**unfurl_kwargs)
    except Exception:
        logger.exception("slack_link_unfurl_chat_unfurl_failed", team_id=team.pk)
