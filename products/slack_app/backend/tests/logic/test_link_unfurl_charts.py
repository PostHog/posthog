import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models import User
from posthog.models.integration import Integration
from posthog.temporal.ai.slack_app.types import (
    SlackAppUnfurlChartsPostInput,
    SlackAppUnfurlChartsWorkflowInputs,
    SlackUnfurlChartAsset,
    SlackUnfurlChartRequest,
)

from products.exports.backend.models.exported_asset import ExportedAsset
from products.product_analytics.backend.facade.models import Insight
from products.slack_app.backend.logic.link_unfurl_charts import (
    chart_cache_key,
    post_unfurl_charts,
    prepare_unfurl_charts,
)

_URL = "https://us.posthog.com/project/1/insights/abc123"
_TEXT_CARD = {"type": "section", "text": {"type": "mrkdwn", "text": "*Weekly active users • Trends insight*"}}


class TestLinkUnfurlCharts(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="TSlack01", sensitive_config={"access_token": "xoxb-test"}
        )
        self.insight = Insight.objects.create(
            team=self.team,
            short_id="abc123",
            name="Weekly active users",
            saved=True,
            query={"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
        )

    def _inputs(self, user: User) -> SlackAppUnfurlChartsWorkflowInputs:
        return SlackAppUnfurlChartsWorkflowInputs(
            team_id=self.team.pk,
            integration_id=self.integration.id,
            user_id=user.pk,
            slack_user_id="U1",
            channel="C1",
            message_ts="123.456",
            unfurl_id=None,
            source=None,
            unfurls={_URL: {"blocks": [_TEXT_CARD]}},
            charts=[SlackUnfurlChartRequest(url=_URL, insight_id=self.insight.id, title="Weekly active users")],
            export_task_queue="unused",
        )

    @parameterized.expand([("same_user", True), ("other_user", False)])
    def test_prepare_reuses_a_cached_render_only_for_the_same_user(self, _name: str, expect_cached: bool) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@example.com", "password")
        key = chart_cache_key(team_id=self.team.pk, insight=self.insight, user_id=self.user.pk)
        cache.set(key, 987654, 60)
        self.addCleanup(cache.delete, key)

        prepared = prepare_unfurl_charts(self._inputs(self.user if expect_cached else other_user))

        assert len(prepared.assets) == 1
        assert prepared.assets[0].cached is expect_cached
        assert (prepared.assets[0].asset_id == 987654) is expect_cached

    @parameterized.expand([("rendered", None, True), ("render_failed", "Export failed", False)])
    @patch("products.slack_app.backend.logic.link_unfurl_charts.SlackIntegration")
    def test_post_adds_the_chart_under_the_title_only_when_the_render_succeeded(
        self, _name: str, exception: str | None, expect_unfurl: bool, mock_slack: MagicMock
    ) -> None:
        asset = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=self.insight,
            content=None if exception else b"png",
            exception=exception,
        )

        post_unfurl_charts(
            SlackAppUnfurlChartsPostInput(
                request=self._inputs(self.user),
                rendered=[SlackUnfurlChartAsset(url=_URL, asset_id=asset.id, cache_key="unused", cached=False)],
                elapsed_ms=1,
            )
        )

        chat_unfurl = mock_slack.return_value.client.chat_unfurl
        if not expect_unfurl:
            chat_unfurl.assert_not_called()
            return
        blocks = chat_unfurl.call_args.kwargs["unfurls"][_URL]["blocks"]
        assert blocks[0] == _TEXT_CARD
        assert blocks[1]["type"] == "image"
        assert blocks[1]["alt_text"] == "Weekly active users"
        assert blocks[1]["image_url"].startswith("http")

    @parameterized.expand(
        [("rejected_payload", "cannot_parse_attachment", False), ("rate_limited", "ratelimited", True)]
    )
    @patch("products.slack_app.backend.logic.link_unfurl_charts.capture_slack_event")
    @patch("products.slack_app.backend.logic.link_unfurl_charts.SlackIntegration")
    def test_post_retries_only_a_rate_limited_unfurl(
        self, _name: str, slack_error: str, expect_raise: bool, mock_slack: MagicMock, mock_capture: MagicMock
    ) -> None:
        asset = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=self.insight,
            content=b"png",
        )
        mock_slack.return_value.client.chat_unfurl.side_effect = SlackApiError(slack_error, {"error": slack_error})
        post = SlackAppUnfurlChartsPostInput(
            request=self._inputs(self.user),
            rendered=[SlackUnfurlChartAsset(url=_URL, asset_id=asset.id, cache_key="unused", cached=False)],
            elapsed_ms=1,
        )

        if expect_raise:
            with pytest.raises(SlackApiError):
                post_unfurl_charts(post)
            mock_capture.assert_not_called()
            return
        post_unfurl_charts(post)
        assert mock_capture.call_args.kwargs["charts_shown"] == 0
        assert mock_capture.call_args.kwargs["failure_reason"] == slack_error
