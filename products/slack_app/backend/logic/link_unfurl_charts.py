"""Chart images for insight link unfurls.

The webhook posts the text card at once, because Slack expects an ack within three seconds and a
render takes longer. ``SlackAppUnfurlChartsWorkflow`` then renders each insight and calls
``chat.unfurl`` again with cards that carry the chart.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings

import structlog
from slack_sdk.errors import SlackApiError
from temporalio.exceptions import ApplicationError

from posthog.models import Team, User
from posthog.models.integration import Integration, SlackIntegration
from posthog.temporal.ai.slack_app.types import (
    SlackAppUnfurlChartsPostInput,
    SlackAppUnfurlChartsPrepared,
    SlackAppUnfurlChartsWorkflowInputs,
    SlackUnfurlChartAsset,
)
from posthog.user_permissions import UserPermissions

from products.exports.backend.facade.api import (
    create_insight_png_export,
    get_delivery_image_url,
    png_export_has_content,
)
from products.product_analytics.backend.facade.api import user_can_view_insight
from products.slack_app.backend.analytics import capture_slack_event

# Slack fetches image_url again after the unfurl is posted, so the token must outlive the post.
_CHART_URL_TTL = timedelta(days=30)
_CHART_ASSET_TTL = timedelta(days=31)
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


def prepare_unfurl_charts(inputs: SlackAppUnfurlChartsWorkflowInputs) -> SlackAppUnfurlChartsPrepared:
    team = Team.objects.get(id=inputs.team_id)
    user = User.objects.get(id=inputs.user_id)
    assets: list[SlackUnfurlChartAsset] = []
    if not _has_project_access(user, team):
        return SlackAppUnfurlChartsPrepared(distinct_id=str(user.distinct_id), assets=assets)
    # Two links to the same insight in one message share one render.
    for insight_id in dict.fromkeys(chart.insight_id for chart in inputs.charts):
        try:
            asset_id = create_insight_png_export(
                team=team,
                created_by=user,
                insight_id=insight_id,
                is_system=True,
                expires_after=datetime.now(UTC) + _CHART_ASSET_TTL,
            )
        except ValueError:
            continue
        assets.append(SlackUnfurlChartAsset(insight_id=insight_id, asset_id=asset_id))
    return SlackAppUnfurlChartsPrepared(distinct_id=str(user.distinct_id), assets=assets)


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


def _image_urls_by_insight(team: Team, user: User, rendered: list[SlackUnfurlChartAsset]) -> dict[int, str]:
    image_urls: dict[int, str] = {}
    for asset in rendered:
        # Checked again because the sharer's access can change while the chart renders.
        if not user_can_view_insight(team=team, user=user, insight_id=asset.insight_id):
            continue
        if not png_export_has_content(team_id=team.pk, asset_id=asset.asset_id):
            continue
        image_url = get_delivery_image_url(
            team_id=team.pk, asset_id=asset.asset_id, expiry_delta=_CHART_URL_TTL, created_by_id=user.pk
        )
        if image_url is not None:
            image_urls[asset.insight_id] = _DEBUG_PLACEHOLDER_IMAGE_URL if settings.DEBUG else image_url
    return image_urls


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


def post_unfurl_charts(post: SlackAppUnfurlChartsPostInput) -> None:
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
        by_insight = _image_urls_by_insight(team, user, post.rendered)
        image_urls = {
            chart.url: by_insight[chart.insight_id] for chart in request.charts if chart.insight_id in by_insight
        }

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
