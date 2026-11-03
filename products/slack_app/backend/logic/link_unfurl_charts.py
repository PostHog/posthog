"""Chart images for insight link unfurls.

The webhook posts the text card at once, because Slack expects an ack within three seconds and a
render takes longer. ``SlackAppUnfurlChartsWorkflow`` then renders each insight and calls
``chat.unfurl`` again with cards that carry the chart.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from django.conf import settings

import structlog
from slack_sdk.errors import SlackApiError
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager
from posthog.models import Team, User
from posthog.models.integration import SlackIntegration
from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.product_analytics.backend.facade.api import user_can_view_insight
from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.services.workspace_integrations import with_teams

if TYPE_CHECKING:
    # Runtime import would load the temporal package, whose activities import this module.
    from products.slack_app.backend.temporal.types import (
        SlackAppUnfurlChartsPostInput,
        SlackAppUnfurlChartsWorkflowInputs,
        SlackUnfurlChartRequest,
    )

_MAX_ALT_TEXT_CHARS = 2000
# A local render has a localhost URL that Slack cannot fetch, and Slack then rejects the whole
# unfurl with cannot_parse_attachment. The same placeholder as subscriptions use in DEBUG.
_DEBUG_PLACEHOLDER_IMAGE_URL = (
    "https://raw.githubusercontent.com/PostHog/posthog/master/frontend/public/icons/android-chrome-512x512.png"
)
# Slack fetches image_url again after the unfurl is posted, so the token must outlive the post.
UNFURL_IMAGE_URL_TTL = timedelta(days=30)
UNFURL_IMAGE_ASSET_TTL = timedelta(days=31)
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


def slack_fetchable_image_url(url: str) -> str:
    local = settings.DEBUG and urlparse(url).hostname in ("localhost", "127.0.0.1")
    return _DEBUG_PLACEHOLDER_IMAGE_URL if local else url


def has_project_access(user: User, team: Team) -> bool:
    # The insight check alone is not enough, because it can fall back to the default access level
    # in a project that denies the user. The webhook checks project access the same way.
    return user.is_active and UserPermissions(user=user, team=team).current_team.effective_membership_level is not None


@frozen
class UnfurlChartTargets:
    team: Team
    user: User
    charts: list[SlackUnfurlChartRequest]


def unfurl_chart_targets(inputs: SlackAppUnfurlChartsWorkflowInputs) -> UnfurlChartTargets:
    team = Team.objects.get(id=inputs.team_id)
    user = User.objects.get(id=inputs.user_id)
    if not has_project_access(user, team):
        return UnfurlChartTargets(team=team, user=user, charts=[])
    # Two links to the same chart in one message share one render.
    unique: dict[str, SlackUnfurlChartRequest] = {}
    for chart in inputs.charts:
        unique.setdefault(chart.render_key, chart)
    return UnfurlChartTargets(team=team, user=user, charts=list(unique.values()))


def _can_view_chart(team: Team, user: User, chart: SlackUnfurlChartRequest, access: UserAccessControl) -> bool:
    if chart.insight_id is not None:
        return user_can_view_insight(team=team, user=user, insight_id=chart.insight_id)
    return access.check_access_level_for_resource("query", "viewer")


def with_chart_images(unfurls: dict[str, Any], image_urls: dict[str, str], titles: dict[str, str]) -> dict[str, Any]:
    """The unfurls with an image block above the buttons of each card that has a chart."""
    result: dict[str, Any] = {}
    for url, payload in unfurls.items():
        blocks = list(payload.get("blocks") or [])
        image_url = image_urls.get(url)
        if image_url is not None:
            alt_text = (titles.get(url) or "Insight chart")[:_MAX_ALT_TEXT_CHARS]
            position = next((i for i, block in enumerate(blocks) if block.get("type") == "actions"), len(blocks))
            blocks.insert(position, {"type": "image", "image_url": image_url, "alt_text": alt_text})
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


def post_unfurl_charts(post: SlackAppUnfurlChartsPostInput, *, image_urls_by_key: dict[str, str]) -> None:
    """Post the rendered charts. ``image_urls_by_key`` holds a delivery url for each render key that rendered."""
    request = post.request
    integration = with_teams([IntegrationManager.slack.oauth.get(request.team_id, request.integration_id)])[0]
    team = integration.team
    user = User.objects.filter(id=request.user_id).first()
    failure_reason: str | None = None
    image_urls: dict[str, str] = {}
    if user is None:
        failure_reason = "user_missing"
    elif not team.organization.allow_publicly_shared_resources:
        # The image url opens without a PostHog login.
        failure_reason = "public_sharing_disabled"
    elif not has_project_access(user, team):
        failure_reason = "no_project_access"
    else:
        # Checked again because the sharer's access can change while the chart renders.
        access = UserAccessControl(user, team=team)
        allowed: dict[str, bool] = {}
        for chart in request.charts:
            key = chart.render_key
            if key not in image_urls_by_key:
                continue
            if key not in allowed:
                allowed[key] = _can_view_chart(team, user, chart, access)
            if allowed[key]:
                image_urls[chart.url] = slack_fetchable_image_url(image_urls_by_key[key])

    adhoc_urls = {chart.url for chart in request.charts if chart.query is not None}
    if image_urls:
        titles = {chart.url: chart.title for chart in request.charts}
        # The webhook posted no card for an ad hoc link, so its card goes out only with its chart.
        unfurls = {url: card for url, card in request.unfurls.items() if url not in adhoc_urls or url in image_urls}
        try:
            SlackIntegration(integration).client.chat_unfurl(
                **chat_unfurl_kwargs(
                    channel=request.channel,
                    ts=request.message_ts,
                    unfurls=with_chart_images(unfurls, image_urls, titles),
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
        adhoc_charts_requested=len(adhoc_urls),
        adhoc_charts_shown=len(adhoc_urls & image_urls.keys()),
        duration_ms=post.elapsed_ms,
        failure_reason=failure_reason,
    )
