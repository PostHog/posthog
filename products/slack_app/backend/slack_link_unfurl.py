"""Slack link unfurling for PostHog insight and dashboard URLs (metadata only)."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

import structlog

from posthog.models import Insight
from posthog.models.integration import Integration, SlackIntegration
from posthog.rbac.user_access_control import UserAccessControl, access_level_satisfied_for_resource

from products.dashboards.backend.models.dashboard import Dashboard

logger = structlog.get_logger(__name__)

_MAX_DESCRIPTION_CHARS = 2800

# Query `source.kind` / top-level `kind` → short name before " insight" (sync with InsightType / query kinds).
_QUERY_KIND_TO_SHORT_NAME: dict[str, str] = {
    "TrendsQuery": "Trends",
    "FunnelsQuery": "Funnel",
    "FunnelCorrelationQuery": "Funnel correlation",
    "RetentionQuery": "Retention",
    "PathsQuery": "Paths",
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


def parse_posthog_resource_link(url: str) -> tuple[Literal["insight", "dashboard"], str | int] | None:
    """
    Parse a PostHog app URL into (resource kind, reference id).

    Reference is insight short_id (str) or dashboard primary key (int).

    If the path includes `/project/:id`, that segment is ignored — lookup is always scoped to the
    Slack-connected project and the resolved PostHog user, not to any project id in the URL.

    Related: `removeProjectIdIfPresent` + `urlToResource` (`router-utils.ts`, `urls.ts`); legacy paths in `get_target_queryset` (`middleware.py`).
    """
    parsed = urlparse(url)
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


def _unfurl_payload(*, resource_label: str, title: str, description: str | None) -> dict:
    title = title or "Untitled"
    body = f"*{title} • {resource_label}*"
    if description:
        body += "\n\n" + _truncate(description.strip(), _MAX_DESCRIPTION_CHARS)
    return {"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": body}}]}


def handle_posthog_link_unfurl(event: dict, integration: Integration) -> None:
    """
    Unfurl PostHog insight/dashboard links with title and description for viewers who may access the resource.

    Scope is always the Slack workspace's connected PostHog project (`integration.team`) and the
    PostHog user resolved from Slack email — never the `/project/:id` segment in pasted URLs.
    """
    slack = SlackIntegration(integration)
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
        return

    user = user_context.user
    team = integration.team
    uac = UserAccessControl(user, team=team)

    unfurls: dict[str, dict] = {}

    for link_obj in links:
        raw_url = link_obj.get("url")
        if not raw_url:
            continue

        parsed = parse_posthog_resource_link(raw_url)
        if not parsed:
            continue

        kind, ref = parsed

        if kind == "insight":
            if not isinstance(ref, str):
                continue
            insight = Insight.objects.filter(team_id=team.pk, short_id=ref).first()
            if not insight:
                continue
            level = uac.get_user_access_level(insight)
            if not level or not access_level_satisfied_for_resource("insight", level, "viewer"):
                continue
            title = insight.name or insight.derived_name or "Untitled"
            desc = (insight.description or "").strip() or None
            unfurls[raw_url] = _unfurl_payload(
                resource_label=_insight_resource_label(insight), title=title, description=desc
            )
        else:
            if not isinstance(ref, int):
                continue
            dashboard = Dashboard.objects.filter(pk=ref, team_id=team.pk).first()
            if not dashboard:
                continue
            level = uac.get_user_access_level(dashboard)
            if not level or not access_level_satisfied_for_resource("dashboard", level, "viewer"):
                continue
            title = dashboard.name or "Untitled"
            desc = (dashboard.description or "").strip() or None
            unfurls[raw_url] = _unfurl_payload(resource_label="Dashboard", title=title, description=desc)

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
