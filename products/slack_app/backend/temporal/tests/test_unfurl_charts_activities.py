from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration import Integration

from products.exports.backend.models.exported_asset import ExportedAsset
from products.product_analytics.backend.facade.models import Insight
from products.slack_app.backend.temporal.activities.unfurl_charts import post_slack_unfurl_charts_activity
from products.slack_app.backend.temporal.types import (
    SlackAppUnfurlChartsPostInput,
    SlackAppUnfurlChartsWorkflowInputs,
    SlackUnfurlChartAsset,
    SlackUnfurlChartRequest,
)

_URL = "https://us.posthog.com/project/1/insights/abc123"


class TestPostSlackUnfurlChartsActivity(BaseTest):
    @parameterized.expand([("rendered", None, True), ("render_failed", "Export failed", False)])
    @patch("products.slack_app.backend.logic.link_unfurl_charts.SlackIntegration")
    def test_posts_a_chart_only_for_a_render_that_stored_its_png(
        self, _name: str, exception: str | None, expect_unfurl: bool, mock_slack: MagicMock
    ) -> None:
        integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="TSlack01", sensitive_config={"access_token": "xoxb-test"}
        )
        insight = Insight.objects.create(team=self.team, short_id="abc123", name="Weekly active users", saved=True)
        asset = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=insight,
            content=None if exception else b"png",
            exception=exception,
        )
        request = SlackAppUnfurlChartsWorkflowInputs(
            team_id=self.team.pk,
            integration_id=integration.id,
            user_id=self.user.pk,
            slack_user_id="U1",
            channel="C1",
            message_ts="123.456",
            unfurl_id=None,
            source=None,
            unfurls={_URL: {"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "*Weekly*"}}]}},
            charts=[SlackUnfurlChartRequest(url=_URL, insight_id=insight.id, title="Weekly active users")],
            export_task_queue="unused",
        )

        post_slack_unfurl_charts_activity(
            SlackAppUnfurlChartsPostInput(
                request=request,
                rendered=[SlackUnfurlChartAsset(render_key=f"insight:{insight.id}", asset_id=asset.id)],
                elapsed_ms=1,
            )
        )

        chat_unfurl = mock_slack.return_value.client.chat_unfurl
        assert chat_unfurl.called is expect_unfurl
