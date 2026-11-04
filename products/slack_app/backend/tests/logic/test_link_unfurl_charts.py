import dataclasses

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from slack_sdk.errors import SlackApiError
from slack_sdk.web.slack_response import SlackResponse
from temporalio.exceptions import ApplicationError

from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.integration import Integration

from products.access_control.backend.models.access_control import AccessControl
from products.product_analytics.backend.facade.models import Insight
from products.slack_app.backend.logic.link_unfurl_charts import post_unfurl_charts, unfurl_chart_targets
from products.slack_app.backend.temporal.types import (
    SlackAppUnfurlChartsPostInput,
    SlackAppUnfurlChartsWorkflowInputs,
    SlackUnfurlChartAsset,
    SlackUnfurlChartRequest,
)

_URL = "https://us.posthog.com/project/1/insights/abc123"
_SHORT_URL = "https://us.posthog.com/i/abc123"
_TITLE = {"type": "section", "text": {"type": "mrkdwn", "text": "📈  *<https://us.posthog.com|Weekly active users>*"}}
_BUTTONS = {"type": "actions", "elements": []}
_ADHOC_URL = "https://us.posthog.com/project/1/insights/new#q=a"
_ADHOC_TITLE = {"type": "section", "text": {"type": "mrkdwn", "text": "📈  *<https://us.posthog.com|Unsaved insight>*"}}
_ADHOC_QUERY = {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": []}}


def _adhoc_chart(url: str = _ADHOC_URL, query: dict | None = None) -> SlackUnfurlChartRequest:
    return SlackUnfurlChartRequest(url=url, query=query or _ADHOC_QUERY, title="Unsaved insight")


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

    def _inputs(self, urls: tuple[str, ...] = (_URL,), user: User | None = None) -> SlackAppUnfurlChartsWorkflowInputs:
        return SlackAppUnfurlChartsWorkflowInputs(
            team_id=self.team.pk,
            integration_id=self.integration.id,
            user_id=(user or self.user).pk,
            slack_user_id="U1",
            channel="C1",
            message_ts="123.456",
            unfurl_id=None,
            source=None,
            unfurls={url: {"blocks": [_TITLE, _BUTTONS]} for url in urls},
            charts=[
                SlackUnfurlChartRequest(url=url, insight_id=self.insight.id, title="Weekly active users")
                for url in urls
            ],
            export_task_queue="unused",
        )

    def _deny_project_access(self) -> User:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
        )
        return User.objects.create_and_join(self.organization, "no-project-access@example.com", "password")

    def _post(
        self, inputs: SlackAppUnfurlChartsWorkflowInputs, rendered: list[SlackUnfurlChartRequest] | None = None
    ) -> None:
        rendered = inputs.charts if rendered is None else rendered
        post_unfurl_charts(
            SlackAppUnfurlChartsPostInput(
                request=inputs,
                rendered=[SlackUnfurlChartAsset(render_key=chart.render_key, asset_id=1) for chart in rendered],
                elapsed_ms=1,
            ),
            image_urls_by_key={chart.render_key: "https://example.com/chart.png" for chart in rendered},
        )

    def _sharer(self, kind: str) -> User:
        if kind == "project_access_revoked":
            return self._deny_project_access()
        if kind == "deactivated":
            self.user.is_active = False
            self.user.save()
        return self.user

    @parameterized.expand(
        [("member", True), ("project_access_revoked", False), ("deactivated", False)],
    )
    def test_targets_render_each_chart_once_and_only_for_an_active_member(
        self, sharer: str, expect_render: bool
    ) -> None:
        user = self._sharer(sharer)
        inputs = self._inputs(urls=(_URL, _SHORT_URL), user=user)
        reordered = {"source": {"series": [], "kind": "TrendsQuery"}, "kind": "InsightVizNode"}
        inputs = dataclasses.replace(
            inputs, charts=[*inputs.charts, _adhoc_chart(), _adhoc_chart(url=_ADHOC_URL + "b", query=reordered)]
        )

        targets = unfurl_chart_targets(inputs)

        expected = [f"insight:{self.insight.id}", _adhoc_chart().render_key] if expect_render else []
        assert [chart.render_key for chart in targets.charts] == expected

    @parameterized.expand(
        [
            ("allowed", True, "member", True),
            ("public_sharing_turned_off", False, "member", False),
            ("project_access_revoked", True, "project_access_revoked", False),
            ("deactivated", True, "deactivated", False),
        ]
    )
    @patch("products.slack_app.backend.logic.link_unfurl_charts.SlackIntegration")
    def test_post_adds_the_chart_above_the_buttons_only_when_allowed(
        self,
        _name: str,
        public_sharing: bool,
        sharer: str,
        expect_unfurl: bool,
        mock_slack: MagicMock,
    ) -> None:
        self.organization.allow_publicly_shared_resources = public_sharing
        self.organization.save()
        user = self._sharer(sharer)

        self._post(self._inputs(user=user))

        chat_unfurl = mock_slack.return_value.client.chat_unfurl
        if not expect_unfurl:
            chat_unfurl.assert_not_called()
            return
        blocks = chat_unfurl.call_args.kwargs["unfurls"][_URL]["blocks"]
        assert [blocks[0], blocks[2]] == [_TITLE, _BUTTONS]
        assert blocks[1]["type"] == "image"
        assert blocks[1]["alt_text"] == "Weekly active users"
        assert blocks[1]["image_url"].startswith("http")

    @parameterized.expand([("adhoc_rendered", True), ("adhoc_render_failed", False)])
    @patch("products.slack_app.backend.logic.link_unfurl_charts.SlackIntegration")
    def test_post_sends_the_adhoc_card_only_with_its_chart(
        self, _name: str, adhoc_rendered: bool, mock_slack: MagicMock
    ) -> None:
        saved = self._inputs()
        inputs = dataclasses.replace(
            saved,
            unfurls={**saved.unfurls, _ADHOC_URL: {"blocks": [_ADHOC_TITLE, _BUTTONS]}},
            charts=[*saved.charts, _adhoc_chart()],
        )

        self._post(inputs, rendered=inputs.charts if adhoc_rendered else saved.charts)

        unfurls = mock_slack.return_value.client.chat_unfurl.call_args.kwargs["unfurls"]
        assert unfurls[_URL]["blocks"][1]["type"] == "image"
        if adhoc_rendered:
            assert [block["type"] for block in unfurls[_ADHOC_URL]["blocks"]] == ["section", "image", "actions"]
        else:
            assert _ADHOC_URL not in unfurls

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
        inputs = self._inputs()

        if expected_raise is not None:
            with pytest.raises(expected_raise) as raised:
                self._post(inputs)
            if isinstance(raised.value, ApplicationError):
                assert raised.value.next_retry_delay is not None
                assert raised.value.next_retry_delay.total_seconds() == 30
            mock_capture.assert_not_called()
            return
        self._post(inputs)
        assert mock_capture.call_args.kwargs["charts_shown"] == 0
        assert mock_capture.call_args.kwargs["failure_reason"] == slack_error
