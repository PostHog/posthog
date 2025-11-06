from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog import settings
from posthog.models.dashboard import Dashboard
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.models.integration import Integration
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.subscription import Subscription

from products.enterprise.backend.tasks.slack import handle_slack_event


def create_mock_unfurl_event(team_id: str, links: list[str]):
    return {
        "token": "XXYYZZ",
        "team_id": team_id,
        "api_app_id": "AXXXXXXXXX",
        "event": {
            "type": "link_shared",
            "channel": "Cxxxxxx",
            "is_bot_user_member": True,
            "user": "Uxxxxxxx",
            "message_ts": "123456789.9875",
            "unfurl_id": "C123456.123456789.987501.1b90fa1278528ce6e2f6c5c2bfa1abc9a41d57d02b29d173f40399c9ffdecf4b",
            "event_ts": "123456621.1855",
            "source": "conversations_history",
            "links": [{"domain": "app.posthog.com", "url": link} for link in links],
        },
        "type": "event_callback",
        "authed_users": ["UXXXXXXX1", "UXXXXXXX2"],
        "event_id": "Ev08MFMKH6",
        "event_time": 123456789,
    }


@patch("ee.tasks.slack.generate_assets")
@patch("ee.tasks.slack.SlackIntegration")
@freeze_time("2022-01-01T12:00:00.000Z")
class TestSlackSubscriptionsTasks(APIBaseTest):
    subscription: Subscription
    dashboard: Dashboard
    insight: Insight
    asset: ExportedAsset
    integration: Integration

    def setUp(self) -> None:
        self.insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")
        self.sharingconfig = SharingConfiguration.objects.create(team=self.team, insight=self.insight, enabled=True)
        self.integration = Integration.objects.create(team=self.team, kind="slack", config={"team": {"id": "T12345"}})
        self.asset = ExportedAsset.objects.create(team=self.team, export_format="image/png", insight=self.insight)

    def test_unfurl_event(self, MockSlackIntegration: MagicMock, mock_generate_assets: MagicMock) -> None:
        mock_slack_integration = MagicMock()
        MockSlackIntegration.return_value = mock_slack_integration
        mock_generate_assets.return_value = ([self.insight], [self.asset])
        mock_slack_integration.client.chat_unfurl.return_value = {"ok": "true"}

        handle_slack_event(
            create_mock_unfurl_event(
                "T12345",
                [
                    f"{settings.SITE_URL}/shared/{self.sharingconfig.access_token}",
                    f"{settings.SITE_URL}/shared/not-found",
                ],
            )
        )

        assert mock_slack_integration.client.chat_unfurl.call_count == 1
        post_message_calls = mock_slack_integration.client.chat_unfurl.call_args_list
        first_call = post_message_calls[0].kwargs

        valid_url = f"{settings.SITE_URL}/shared/{self.sharingconfig.access_token}"

        assert first_call == {
            "unfurls": {
                valid_url: {
                    "blocks": [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "My Test subscription"},
                            "accessory": {
                                "type": "image",
                                "image_url": first_call["unfurls"][valid_url]["blocks"][0]["accessory"]["image_url"],
                                "alt_text": "My Test subscription",
                            },
                        }
                    ]
                }
            },
            "unfurl_id": "C123456.123456789.987501.1b90fa1278528ce6e2f6c5c2bfa1abc9a41d57d02b29d173f40399c9ffdecf4b",
            "source": "conversations_history",
            "channel": "",
            "ts": "",
        }
