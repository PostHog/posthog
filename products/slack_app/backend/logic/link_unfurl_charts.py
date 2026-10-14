"""Chart images for insight link unfurls.

The webhook posts the text card at once, because Slack expects an ack within three seconds and a
render takes longer. ``SlackAppUnfurlChartsWorkflow`` then renders each insight and calls
``chat.unfurl`` again with cards that carry the chart.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.core.cache import cache

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models import Team, User
from posthog.models.integration import Integration, SlackIntegration
from posthog.temporal.ai.slack_app.types import (
    SlackAppUnfurlChartsPostInput,
    SlackAppUnfurlChartsPrepared,
    SlackAppUnfurlChartsWorkflowInputs,
    SlackUnfurlChartAsset,
)

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.exports.backend.facade.api import create_png_export_asset, get_delivery_image_url, png_export_has_content
from products.product_analytics.backend.facade.models import Insight
from products.slack_app.backend.analytics import capture_slack_event

# Slack fetches image_url again after the unfurl is posted, so the token must outlive the post.
_CHART_URL_TTL = timedelta(days=30)
_CHART_ASSET_TTL = timedelta(days=31)
_CHART_CACHE_SECONDS = 10 * 60
_MAX_ALT_TEXT_CHARS = 2000
# A local render has a localhost URL that Slack cannot fetch, and Slack then rejects the whole
# unfurl with cannot_parse_attachment. The same placeholder as subscriptions use in DEBUG.
_DEBUG_PLACEHOLDER_IMAGE_URL = (
    "https://raw.githubusercontent.com/PostHog/posthog/master/frontend/public/icons/android-chrome-512x512.png"
)

logger = structlog.get_logger(__name__)


def chart_cache_key(*, team_id: int, insight: Insight, user_id: int) -> str:
    # The user is in the key because the render runs with that user's access.
    return f"slack_app:unfurl_chart:v1:{team_id}:{insight.id}:{int(insight.updated_at.timestamp())}:{user_id}"


def chat_unfurl_kwargs(
    *, channel: str, ts: str, unfurls: dict[str, Any], unfurl_id: str | None, source: str | None
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"channel": channel, "ts": ts, "unfurls": unfurls}
    if unfurl_id:
        kwargs["unfurl_id"] = unfurl_id
    if source:
        kwargs["source"] = source
    return kwargs


def prepare_unfurl_charts(inputs: SlackAppUnfurlChartsWorkflowInputs) -> SlackAppUnfurlChartsPrepared:
    team = Team.objects.get(id=inputs.team_id)
    user = User.objects.get(id=inputs.user_id)
    access = UserAccessControl(user, team=team)
    assets: list[SlackUnfurlChartAsset] = []
    for chart in inputs.charts:
        insight = Insight.objects.filter(team_id=team.pk, id=chart.insight_id, deleted=False).first()
        if insight is None:
            continue
        cache_key = chart_cache_key(team_id=team.pk, insight=insight, user_id=user.pk)
        cached_asset_id = cache.get(cache_key)
        if isinstance(cached_asset_id, int):
            # Checked again here because access can change between the render and a later paste.
            # create_png_export_asset runs the same check for a new render.
            if access.check_access_level_for_object(insight, "viewer"):
                assets.append(
                    SlackUnfurlChartAsset(url=chart.url, asset_id=cached_asset_id, cache_key=cache_key, cached=True)
                )
            continue
        try:
            asset = create_png_export_asset(
                team=team,
                created_by=user,
                insight_id=insight.id,
                is_system=True,
                expires_after=datetime.now(UTC) + _CHART_ASSET_TTL,
            )
        except ValueError:
            continue
        assets.append(SlackUnfurlChartAsset(url=chart.url, asset_id=asset.id, cache_key=cache_key, cached=False))
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


def post_unfurl_charts(post: SlackAppUnfurlChartsPostInput) -> None:
    request = post.request
    integration = Integration.objects.select_related("team").get(id=request.integration_id, team_id=request.team_id)
    image_urls: dict[str, str] = {}
    for asset in post.rendered:
        if not asset.cached and not png_export_has_content(team_id=integration.team_id, asset_id=asset.asset_id):
            continue
        # created_by_id pins a cached id to the user that rendered it.
        image_url = get_delivery_image_url(
            team_id=integration.team_id,
            asset_id=asset.asset_id,
            expiry_delta=_CHART_URL_TTL,
            created_by_id=request.user_id,
        )
        if image_url is None:
            continue
        image_urls[asset.url] = _DEBUG_PLACEHOLDER_IMAGE_URL if settings.DEBUG else image_url
        if not asset.cached:
            cache.set(asset.cache_key, asset.asset_id, _CHART_CACHE_SECONDS)

    failure_reason: str | None = None
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
            error = e.response.get("error") if e.response is not None else None
            # A retry cannot fix a payload that Slack rejects, so only a rate limit raises for
            # Temporal to retry. Network errors are not SlackApiError and also raise.
            if error == "ratelimited":
                raise
            logger.warning("slack_app_unfurl_charts_rejected", team_id=integration.team_id, error=error)
            failure_reason = error or "slack_api_error"
            image_urls = {}

    capture_slack_event(
        integration,
        "slack app link unfurl charts",
        slack_user_id=request.slack_user_id,
        posthog_user=User.objects.filter(id=request.user_id).first(),
        charts_requested=len(request.charts),
        charts_shown=len(image_urls),
        charts_cached=sum(1 for asset in post.rendered if asset.cached and asset.url in image_urls),
        charts_failed=len(request.charts) - len(image_urls),
        duration_ms=post.elapsed_ms,
        failure_reason=failure_reason,
    )
