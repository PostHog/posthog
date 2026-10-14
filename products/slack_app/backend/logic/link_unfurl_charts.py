"""Chart images for insight link unfurls.

The webhook posts the text card at once, because Slack expects an ack within three seconds and a
render takes longer. ``SlackAppUnfurlChartsWorkflow`` then renders each insight and calls
``chat.unfurl`` again with cards that carry the chart.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings

import structlog
from slack_sdk.errors import SlackApiError
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.models.integration import Integration, SlackIntegration
from posthog.temporal.ai.slack_app.types import SlackAppUnfurlChartsPostInput, SlackAppUnfurlChartsWorkflowInputs
from posthog.user_permissions import UserPermissions

from products.product_analytics.backend.facade.api import user_can_view_insight
from products.slack_app.backend.analytics import capture_slack_event

_MAX_ALT_TEXT_CHARS = 2000
# A local render has a localhost URL that Slack cannot fetch, and Slack then rejects the whole
# unfurl with cannot_parse_attachment. The same placeholder as subscriptions use in DEBUG.
_DEBUG_PLACEHOLDER_IMAGE_URL = (
    "https://raw.githubusercontent.com/PostHog/posthog/master/frontend/public/icons/android-chrome-512x512.png"
)
# Slack errors that a later attempt can fix. Any other error means Slack rejects the payload itself.
_TRANSIENT_SLACK_ERRORS = frozenset(
    {"ratelimited", "internal_error", "fatal_error", "service_unavailable", "request_timeout"}
)

logger = structlog.get_logger(__name__)


def chat_unfurl_kwargs(
    *, channel: str, ts: str, unfurls: dict[str, Any], unfurl_id: str | None, source: str | None
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"channel": channel, "ts": ts, "unfurls": unfurls}
    if unfurl_id:
        kwargs["unfurl_id"] = unfurl_id
    if source:
        kwargs["source"] = source
    return kwargs


def _has_project_access(user: User, team: Team) -> bool:
    # The insight check alone is not enough, because it can fall back to the default access level
    # in a project that denies the user. The webhook checks project access the same way.
    return UserPermissions(user=user, team=team).current_team.effective_membership_level is not None


@frozen
class UnfurlChartTargets:
    team: Team
    user: User
    insight_ids: list[int]


def unfurl_chart_targets(inputs: SlackAppUnfurlChartsWorkflowInputs) -> UnfurlChartTargets:
    team = Team.objects.get(id=inputs.team_id)
    user = User.objects.get(id=inputs.user_id)
    if not _has_project_access(user, team):
        return UnfurlChartTargets(team=team, user=user, insight_ids=[])
    # Two links to the same insight in one message share one render.
    insight_ids = list(dict.fromkeys(chart.insight_id for chart in inputs.charts))
    return UnfurlChartTargets(team=team, user=user, insight_ids=insight_ids)


def with_chart_images(unfurls: dict[str, Any], image_urls: dict[str, str], titles: dict[str, str]) -> dict[str, Any]:
    """The unfurls with an image block under the title of each card that has a chart."""
    result: dict[str, Any] = {}
    for url, payload in unfurls.items():
        blocks = list(payload.get("blocks") or [])
        image_url = image_urls.get(url)
        if image_url is not None:
            alt_text = (titles.get(url) or "Insight chart")[:_MAX_ALT_TEXT_CHARS]
            blocks.insert(1, {"type": "image", "image_url": image_url, "alt_text": alt_text})
        result[url] = {**payload, "blocks": blocks}
    return result


def _raise_if_transient(error: SlackApiError) -> None:
    response = error.response
    code = response.get("error") if response is not None else None
    if code == "ratelimited" and response is not None:
        retry_after = int(response.headers.get("Retry-After", 0) or 0)
        # The fixed retry interval is often shorter than the wait that Slack asks for.
        raise ApplicationError(
            "Slack rate limited chat.unfurl", next_retry_delay=timedelta(seconds=max(retry_after, 1))
        ) from error
    if code in _TRANSIENT_SLACK_ERRORS or (response is not None and response.status_code >= 500):
        raise error


def post_unfurl_charts(post: SlackAppUnfurlChartsPostInput, *, image_urls_by_insight: dict[int, str]) -> None:
    """Post the rendered charts. ``image_urls_by_insight`` holds a delivery url for each insight that rendered."""
    request = post.request
    integration = Integration.objects.select_related("team__organization").get(
        id=request.integration_id, team_id=request.team_id
    )
    team = integration.team
    user = User.objects.filter(id=request.user_id).first()
    failure_reason: str | None = None
    image_urls: dict[str, str] = {}
    if user is None:
        failure_reason = "user_missing"
    elif not team.organization.allow_publicly_shared_resources:
        # The image url opens without a PostHog login.
        failure_reason = "public_sharing_disabled"
    elif not _has_project_access(user, team):
        failure_reason = "no_project_access"
    else:
        # Checked again because the sharer's access can change while the chart renders.
        allowed = {
            insight_id: _DEBUG_PLACEHOLDER_IMAGE_URL if settings.DEBUG else url
            for insight_id, url in image_urls_by_insight.items()
            if user_can_view_insight(team=team, user=user, insight_id=insight_id)
        }
        image_urls = {chart.url: allowed[chart.insight_id] for chart in request.charts if chart.insight_id in allowed}

    if image_urls:
        titles = {chart.url: chart.title for chart in request.charts}
        try:
            SlackIntegration(integration).client.chat_unfurl(
                **chat_unfurl_kwargs(
                    channel=request.channel,
                    ts=request.message_ts,
                    unfurls=with_chart_images(request.unfurls, image_urls, titles),
                    unfurl_id=request.unfurl_id,
                    source=request.source,
                )
            )
        except SlackApiError as e:
            _raise_if_transient(e)
            error = e.response.get("error") if e.response is not None else None
            logger.warning("slack_app_unfurl_charts_rejected", team_id=team.pk, error=error)
            failure_reason = error or "slack_api_error"
            image_urls = {}

    capture_slack_event(
        integration,
        "slack app link unfurl charts",
        slack_user_id=request.slack_user_id,
        posthog_user=user,
        charts_requested=len(request.charts),
        charts_shown=len(image_urls),
        charts_failed=len(request.charts) - len(image_urls),
        duration_ms=post.elapsed_ms,
        failure_reason=failure_reason,
    )
