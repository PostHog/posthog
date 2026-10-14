"""Chart images for insight link unfurls.

The webhook posts the text card at once, because Slack expects an ack within three seconds and a
render takes longer. ``SlackAppUnfurlChartsWorkflow`` then renders each insight and calls
``chat.unfurl`` again with cards that carry the chart.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.cache import cache

from posthog.models import User
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
# The same TTLs as alert charts.
_CHART_URL_TTL = timedelta(days=30)
_CHART_ASSET_TTL = timedelta(days=31)
# A link that people paste again and again in a short time uses one render.
_CHART_CACHE_SECONDS = 10 * 60
_MAX_ALT_TEXT_CHARS = 2000


def chart_cache_key(*, team_id: int, insight: Insight, user_id: int) -> str:
    # The user is in the key because the render runs with that user's access.
    return f"slack_app:unfurl_chart:v1:{team_id}:{insight.id}:{int(insight.updated_at.timestamp())}:{user_id}"


def prepare_unfurl_charts(inputs: SlackAppUnfurlChartsWorkflowInputs) -> SlackAppUnfurlChartsPrepared:
    """Find a cached PNG for each chart, or create the export asset the workflow renders."""
    integration = Integration.objects.select_related("team").get(id=inputs.integration_id, team_id=inputs.team_id)
    team = integration.team
    user = User.objects.get(id=inputs.user_id)
    access = UserAccessControl(user, team=team)
    assets: list[SlackUnfurlChartAsset] = []
    refused_count = 0
    for chart in inputs.charts:
        insight = Insight.objects.filter(team_id=team.pk, id=chart.insight_id, deleted=False).first()
        # Checked again here: access can change between the paste and the render.
        if insight is None or not access.check_access_level_for_object(insight, "viewer"):
            refused_count += 1
            continue
        cache_key = chart_cache_key(team_id=team.pk, insight=insight, user_id=user.pk)
        cached_asset_id = cache.get(cache_key)
        if isinstance(cached_asset_id, int):
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
            refused_count += 1
            continue
        assets.append(SlackUnfurlChartAsset(url=chart.url, asset_id=asset.id, cache_key=cache_key, cached=False))
    return SlackAppUnfurlChartsPrepared(distinct_id=str(user.distinct_id), assets=assets, refused_count=refused_count)


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
    """Replace the text cards with cards that carry the rendered charts, and record the outcome."""
    request = post.request
    integration = Integration.objects.select_related("team").get(id=request.integration_id, team_id=request.team_id)
    image_urls: dict[str, str] = {}
    failed_count = post.failed_count
    for asset in post.rendered:
        if not asset.cached and not png_export_has_content(team_id=integration.team_id, asset_id=asset.asset_id):
            failed_count += 1
            continue
        # created_by_id pins a cached id to the user that rendered it.
        image_url = get_delivery_image_url(
            team_id=integration.team_id,
            asset_id=asset.asset_id,
            expiry_delta=_CHART_URL_TTL,
            created_by_id=request.user_id,
        )
        if image_url is None:
            failed_count += 1
            continue
        image_urls[asset.url] = image_url
        if not asset.cached:
            cache.set(asset.cache_key, asset.asset_id, _CHART_CACHE_SECONDS)

    if image_urls:
        titles = {chart.url: chart.title for chart in request.charts}
        unfurl_kwargs: dict[str, Any] = {
            "channel": request.channel,
            "ts": request.message_ts,
            "unfurls": with_chart_images(request.unfurls, image_urls, titles),
        }
        if request.unfurl_id:
            unfurl_kwargs["unfurl_id"] = request.unfurl_id
        if request.source:
            unfurl_kwargs["source"] = request.source
        # A failure raises, so Temporal retries this step without a new render.
        SlackIntegration(integration).client.chat_unfurl(**unfurl_kwargs)

    capture_slack_event(
        integration,
        "slack app link unfurl charts",
        slack_user_id=request.slack_user_id,
        posthog_user=User.objects.filter(id=request.user_id).first(),
        charts_requested=len(request.charts),
        charts_shown=len(image_urls),
        charts_cached=sum(1 for asset in post.rendered if asset.cached and asset.url in image_urls),
        charts_failed=failed_count,
        duration_ms=post.elapsed_ms,
    )
