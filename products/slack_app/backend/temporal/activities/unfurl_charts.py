from datetime import UTC, datetime

from temporalio import activity

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.temporal.common.utils import close_db_connections

from products.exports.backend.facade.api import create_png_export, get_delivery_image_url, png_export_has_content
from products.slack_app.backend.logic.link_unfurl_charts import (
    UNFURL_IMAGE_ASSET_TTL,
    UNFURL_IMAGE_URL_TTL,
    post_unfurl_charts,
    unfurl_chart_targets,
)
from products.slack_app.backend.temporal.types import (
    SlackAppUnfurlChartsPostInput,
    SlackAppUnfurlChartsPrepared,
    SlackAppUnfurlChartsWorkflowInputs,
    SlackUnfurlChartAsset,
)


@activity.defn
@close_db_connections
def prepare_slack_unfurl_charts_activity(inputs: SlackAppUnfurlChartsWorkflowInputs) -> SlackAppUnfurlChartsPrepared:
    targets = unfurl_chart_targets(inputs)
    assets: list[SlackUnfurlChartAsset] = []
    expires_after = datetime.now(UTC) + UNFURL_IMAGE_ASSET_TTL
    for chart in targets.charts:
        try:
            asset_id = create_png_export(
                team=targets.team,
                created_by=targets.user,
                insight_id=chart.insight_id,
                query=chart.query,
                is_system=True,
                expires_after=expires_after,
                # A recent cached result is fresh enough for a preview and saves a query per unfurl.
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            )
        except ValueError:
            continue
        assets.append(
            SlackUnfurlChartAsset(render_key=chart.render_key, insight_id=chart.insight_id, asset_id=asset_id)
        )
    return SlackAppUnfurlChartsPrepared(distinct_id=str(targets.user.distinct_id), assets=assets)


@activity.defn
@close_db_connections
def post_slack_unfurl_charts_activity(post: SlackAppUnfurlChartsPostInput) -> None:
    request = post.request
    image_urls_by_key: dict[str, str] = {}
    for asset in post.rendered:
        if not png_export_has_content(team_id=request.team_id, asset_id=asset.asset_id):
            continue
        # created_by_id ties the asset to the sharer who rendered it.
        image_url = get_delivery_image_url(
            team_id=request.team_id,
            asset_id=asset.asset_id,
            expiry_delta=UNFURL_IMAGE_URL_TTL,
            created_by_id=request.user_id,
        )
        if image_url is not None:
            image_urls_by_key[asset.render_key] = image_url
    post_unfurl_charts(post, image_urls_by_key=image_urls_by_key)
