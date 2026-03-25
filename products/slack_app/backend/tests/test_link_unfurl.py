import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.models import Dashboard, Insight
from posthog.models.integration import Integration

from products.slack_app.backend.slack_link_unfurl import (
    _insight_resource_label,
    handle_posthog_link_unfurl,
    parse_posthog_resource_link,
)


class TestParsePosthogResourceLink:
    def test_project_insight(self):
        assert parse_posthog_resource_link("https://us.posthog.com/project/42/insights/abc123") == ("insight", "abc123")

    def test_project_insight_with_subpath(self):
        assert parse_posthog_resource_link("https://eu.posthog.com/project/42/insights/abc123/edit") == (
            "insight",
            "abc123",
        )

    def test_short_insight_path(self):
        assert parse_posthog_resource_link("https://app.posthog.com/i/xyz789") == ("insight", "xyz789")

    def test_project_dashboard(self):
        assert parse_posthog_resource_link("https://us.posthog.com/project/3/dashboard/99") == ("dashboard", 99)

    def test_skips_insight_new(self):
        assert parse_posthog_resource_link("https://x.com/project/1/insights/new") is None

    def test_unrelated_url(self):
        assert parse_posthog_resource_link("https://example.com/foo") is None


class TestInsightResourceLabel:
    def test_insight_viz_trends(self):
        insight = Insight(
            team_id=1,
            query={"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
        )
        assert _insight_resource_label(insight) == "Trends insight"

    def test_data_viz_sql(self):
        insight = Insight(
            team_id=1,
            query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "SELECT 1"}},
        )
        assert _insight_resource_label(insight) == "SQL insight"

    def test_legacy_filters(self):
        insight = Insight(team_id=1, filters={"insight": "FUNNELS"})
        assert _insight_resource_label(insight) == "Funnel insight"

    def test_fallback(self):
        insight = Insight(team_id=1)
        assert _insight_resource_label(insight) == "Insight"


@pytest.mark.django_db
class TestHandlePosthogLinkUnfurl(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="TSlack01",
            sensitive_config={"access_token": "xoxb-test"},
        )
        self.insight = Insight.objects.create(
            team=self.team,
            short_id="insight1",
            name="Weekly active users",
            description="A test description",
            saved=True,
            query={"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
        )

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_unfurls_insight_when_user_resolved(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        site = "http://testserver"
        url = f"{site}/project/{self.team.pk}/insights/{self.insight.short_id}"

        handle_posthog_link_unfurl(
            {
                "channel": "C1",
                "message_ts": "123.456",
                "user": "U1",
                "links": [{"url": url, "domain": "testserver"}],
            },
            self.integration,
        )

        mock_client.chat_unfurl.assert_called_once()
        call_kw = mock_client.chat_unfurl.call_args.kwargs
        assert url in call_kw["unfurls"]
        text = call_kw["unfurls"][url]["blocks"][0]["text"]["text"]
        assert "Trends insight" in text
        assert "Weekly active users" in text
        assert "A test description" in text

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_skips_when_user_not_resolved(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        mock_resolve.return_value = None
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        handle_posthog_link_unfurl(
            {
                "channel": "C1",
                "message_ts": "123.456",
                "user": "U1",
                "links": [{"url": f"http://testserver/project/{self.team.pk}/insights/{self.insight.short_id}"}],
            },
            self.integration,
        )

        mock_client.chat_unfurl.assert_not_called()

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_unfurls_insight_when_project_segment_mismatched(
        self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock
    ) -> None:
        """Project id in the URL is ignored; lookup uses the connected team + short_id only."""
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        url = f"http://testserver/project/99999/insights/{self.insight.short_id}"
        handle_posthog_link_unfurl(
            {
                "channel": "C1",
                "message_ts": "123.456",
                "user": "U1",
                "links": [{"url": url}],
            },
            self.integration,
        )

        mock_client.chat_unfurl.assert_called_once()
        assert url in mock_client.chat_unfurl.call_args.kwargs["unfurls"]

    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("products.slack_app.backend.slack_link_unfurl.SlackIntegration")
    def test_unfurls_dashboard(self, mock_slack_integration_class: MagicMock, mock_resolve: MagicMock) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Main board", description="Overview")
        mock_resolve.return_value = MagicMock(user=self.user)
        mock_client = MagicMock()
        mock_slack_integration_class.return_value.client = mock_client

        site = "http://testserver"
        url = f"{site}/project/{self.team.pk}/dashboard/{dashboard.pk}"

        handle_posthog_link_unfurl(
            {
                "channel": "C1",
                "message_ts": "123.456",
                "user": "U1",
                "links": [{"url": url}],
            },
            self.integration,
        )

        mock_client.chat_unfurl.assert_called_once()
        text = mock_client.chat_unfurl.call_args.kwargs["unfurls"][url]["blocks"][0]["text"]["text"]
        assert "Dashboard" in text
        assert "Main board" in text
