import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from slack_sdk.errors import SlackApiError
from slack_sdk.web.slack_response import SlackResponse
from temporalio.exceptions import ApplicationError

from posthog.models.integration import Integration
from posthog.temporal.ai.slack_app.types import (
    SlackAppUnfurlChartsPostInput,
    SlackAppUnfurlChartsWorkflowInputs,
    SlackUnfurlChartAsset,
    SlackUnfurlChartRequest,
)

from products.exports.backend.models.exported_asset import ExportedAsset
from products.product_analytics.backend.facade.models import Insight
from products.slack_app.backend.logic.link_unfurl_charts import post_unfurl_charts, prepare_unfurl_charts

_URL = "https://us.posthog.com/project/1/insights/abc123"
_SHORT_URL = "https://us.posthog.com/i/abc123"
_TEXT_CARD = {"type": "section", "text": {"type": "mrkdwn", "text": "*Weekly active users • Trends insight*"}}


def _slack_error(code: str, status_code: int) -> SlackApiError:
    response = SlackResponse(
        client=None,
        http_verb="POST",
        api_url="https://slack.com/api/chat.unfurl",
        req_args={},
        data={"ok": False, "error": code},
        headers={"Retry-After": "30"},
        status_code=status_code,
    )
    return SlackApiError(code, response)


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

    def _inputs(self, urls: tuple[str, ...] = (_URL,)) -> SlackAppUnfurlChartsWorkflowInputs:
        return SlackAppUnfurlChartsWorkflowInputs(
            team_id=self.team.pk,
            integration_id=self.integration.id,
            user_id=self.user.pk,
            slack_user_id="U1",
            channel="C1",
            message_ts="123.456",
            unfurl_id=None,
            source=None,
            unfurls={url: {"blocks": [_TEXT_CARD]} for url in urls},
            charts=[
                SlackUnfurlChartRequest(url=url, insight_id=self.insight.id, title="Weekly active users")
                for url in urls
            ],
            export_task_queue="unused",
        )

    def _post(self, inputs: SlackAppUnfurlChartsWorkflowInputs, asset: ExportedAsset) -> None:
        post_unfurl_charts(
            SlackAppUnfurlChartsPostInput(
                request=inputs,
                rendered=[SlackUnfurlChartAsset(insight_id=self.insight.id, asset_id=asset.id)],
                elapsed_ms=1,
            )
        )

    def _asset(self, exception: str | None = None) -> ExportedAsset:
        return ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=self.insight,
            content=None if exception else b"png",
            exception=exception,
        )

    def test_prepare_renders_an_insight_once_for_two_links_to_it(self) -> None:
        prepared = prepare_unfurl_charts(self._inputs(urls=(_URL, _SHORT_URL)))

        assert [asset.insight_id for asset in prepared.assets] == [self.insight.id]

    @parameterized.expand(
        [
            ("rendered", None, True, True),
            ("render_failed", "Export failed", True, False),
            ("public_sharing_turned_off", None, False, False),
        ]
    )
    @patch("products.slack_app.backend.logic.link_unfurl_charts.SlackIntegration")
    def test_post_adds_the_chart_under_the_title_only_when_allowed(
        self, _name: str, exception: str | None, public_sharing: bool, expect_unfurl: bool, mock_slack: MagicMock
    ) -> None:
        self.organization.allow_publicly_shared_resources = public_sharing
        self.organization.save()

        self._post(self._inputs(), self._asset(exception))

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
        [
            ("rejected_payload", "cannot_parse_attachment", 200, None),
            ("rate_limited", "ratelimited", 429, ApplicationError),
            ("slack_outage", "internal_error", 500, SlackApiError),
        ]
    )
    @patch("products.slack_app.backend.logic.link_unfurl_charts.capture_slack_event")
    @patch("products.slack_app.backend.logic.link_unfurl_charts.SlackIntegration")
    def test_post_retries_only_a_transient_slack_error(
        self,
        _name: str,
        slack_error: str,
        status_code: int,
        expected_raise: type[Exception] | None,
        mock_slack: MagicMock,
        mock_capture: MagicMock,
    ) -> None:
        mock_slack.return_value.client.chat_unfurl.side_effect = _slack_error(slack_error, status_code)
        inputs, asset = self._inputs(), self._asset()

        if expected_raise is not None:
            with pytest.raises(expected_raise) as raised:
                self._post(inputs, asset)
            if isinstance(raised.value, ApplicationError):
                assert raised.value.next_retry_delay is not None
                assert raised.value.next_retry_delay.total_seconds() == 30
            mock_capture.assert_not_called()
            return
        self._post(inputs, asset)
        assert mock_capture.call_args.kwargs["charts_shown"] == 0
        assert mock_capture.call_args.kwargs["failure_reason"] == slack_error
