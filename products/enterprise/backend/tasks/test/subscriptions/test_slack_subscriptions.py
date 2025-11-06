import asyncio

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.models.dashboard import Dashboard
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.models.integration import Integration
from posthog.models.subscription import Subscription

from products.enterprise.backend.tasks.subscriptions.slack_subscriptions import (
    send_slack_message_with_integration_async,
    send_slack_subscription_report,
)
from products.enterprise.backend.tasks.test.subscriptions.subscriptions_test_factory import create_subscription


@patch("products.enterprise.backend.tasks.subscriptions.slack_subscriptions.SlackIntegration")
@freeze_time("2022-02-02T08:30:00.000Z")
class TestSlackSubscriptionsTasks(APIBaseTest):
    subscription: Subscription
    dashboard: Dashboard
    insight: Insight
    asset: ExportedAsset
    integration: Integration

    def setUp(self) -> None:
        self.dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        self.insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")
        self.asset = ExportedAsset.objects.create(team=self.team, insight_id=self.insight.id, export_format="image/png")
        self.subscription = create_subscription(
            team=self.team,
            insight=self.insight,
            created_by=self.user,
            target_type="slack",
            target_value="C12345|#test-channel",
        )

        self.integration = Integration.objects.create(team=self.team, kind="slack")

    def test_subscription_delivery(self, MockSlackIntegration: MagicMock) -> None:
        mock_slack_integration = MagicMock()
        MockSlackIntegration.return_value = mock_slack_integration
        mock_slack_integration.client.chat_postMessage.return_value = {"ts": "1.234"}

        send_slack_subscription_report(self.subscription, [self.asset], 1)

        assert mock_slack_integration.client.chat_postMessage.call_count == 1
        post_message_calls = mock_slack_integration.client.chat_postMessage.call_args_list
        first_call = post_message_calls[0].kwargs

        assert first_call["channel"] == "C12345"
        assert first_call["text"] == "Your subscription to the Insight *My Test subscription* is ready! 🎉"
        assert first_call["blocks"] == [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Your subscription to the Insight *My Test subscription* is ready! 🎉",
                },
            },
            {
                "type": "image",
                "image_url": post_message_calls[0].kwargs["blocks"][1]["image_url"],
                "alt_text": "My Test subscription",
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View in PostHog"},
                        "url": "http://localhost:8010/insights/123456?utm_source=posthog&utm_campaign=subscription_report&utm_medium=slack",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Manage Subscription"},
                        "url": f"http://localhost:8010/insights/123456/subscriptions/{self.subscription.id}?utm_source=posthog&utm_campaign=subscription_report&utm_medium=slack",
                    },
                ],
            },
        ]

    def test_subscription_delivery_new(self, MockSlackIntegration: MagicMock) -> None:
        mock_slack_integration = MagicMock()
        MockSlackIntegration.return_value = mock_slack_integration
        mock_slack_integration.client.chat_postMessage.return_value = {"ts": "1.234"}

        send_slack_subscription_report(self.subscription, [self.asset], 1, is_new_subscription=True)

        assert mock_slack_integration.client.chat_postMessage.call_count == 1
        post_message_calls = mock_slack_integration.client.chat_postMessage.call_args_list
        first_call = post_message_calls[0].kwargs

        assert (
            first_call["text"]
            == "This channel has been subscribed to the Insight *My Test subscription* on PostHog! 🎉\nThis subscription is sent every day. The next one will be sent on Wednesday February 02, 2022"
        )

    def test_subscription_dashboard_delivery(self, MockSlackIntegration: MagicMock) -> None:
        mock_slack_integration = MagicMock()
        MockSlackIntegration.return_value = mock_slack_integration
        mock_slack_integration.client.chat_postMessage.return_value = {"ts": "1.234"}

        self.subscription = create_subscription(
            team=self.team,
            dashboard=self.dashboard,
            created_by=self.user,
            target_type="slack",
            target_value="C12345|#test-channel",
        )

        send_slack_subscription_report(self.subscription, [self.asset, self.asset, self.asset], 10)

        assert mock_slack_integration.client.chat_postMessage.call_count == 4
        post_message_calls = mock_slack_integration.client.chat_postMessage.call_args_list
        first_call = post_message_calls[0].kwargs

        assert first_call["channel"] == "C12345"
        assert first_call["text"] == "Your subscription to the Dashboard *private dashboard* is ready! 🎉"

        assert first_call["blocks"] == [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Your subscription to the Dashboard *private dashboard* is ready! 🎉",
                },
            },
            {
                "type": "image",
                "image_url": post_message_calls[0].kwargs["blocks"][1]["image_url"],
                "alt_text": "My Test subscription",
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_See 🧵 for more Insights_"},
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View in PostHog"},
                        "url": f"http://localhost:8010/dashboard/{self.dashboard.id}?utm_source=posthog&utm_campaign=subscription_report&utm_medium=slack",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Manage Subscription"},
                        "url": f"http://localhost:8010/dashboard/{self.dashboard.id}/subscriptions/{self.subscription.id}?utm_source=posthog&utm_campaign=subscription_report&utm_medium=slack",
                    },
                ],
            },
        ]

        # Second call - other asset
        second_call = post_message_calls[1].kwargs
        assert second_call["channel"] == "C12345"
        assert second_call["thread_ts"] == "1.234"
        assert second_call["blocks"] == [
            {
                "type": "image",
                "image_url": second_call["blocks"][0]["image_url"],
                "alt_text": "My Test subscription",
            }
        ]

        # Third call - other asset
        third_call = post_message_calls[2].kwargs
        assert third_call["blocks"] == [
            {
                "type": "image",
                "image_url": third_call["blocks"][0]["image_url"],
                "alt_text": "My Test subscription",
            }
        ]

        # Fourth call - notice that more exists
        fourth_call = post_message_calls[3].kwargs
        assert fourth_call["blocks"] == [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Showing 3 of 10 Insights. <http://localhost:8010/dashboard/{self.dashboard.id}?utm_source=posthog&utm_campaign=subscription_report&utm_medium=slack|View the rest in PostHog>",
                },
            }
        ]

    def test_subscription_delivery_missing_integration(self, MockSlackIntegration: MagicMock) -> None:
        mock_slack_integration = MagicMock()
        MockSlackIntegration.return_value = mock_slack_integration

        self.integration.delete()

        send_slack_subscription_report(self.subscription, [self.asset], 1)

        assert mock_slack_integration.client.chat_postMessage.call_count == 0

        # TODO: Should we perhaps save something to say the Subscription failed?


@patch("products.enterprise.backend.tasks.subscriptions.slack_subscriptions.SlackIntegration")
@freeze_time("2025-01-01T08:30:00.000Z")
class TestSlackSubscriptionsAsyncTasks(APIBaseTest):
    TOTAL_ASSET_COUNT = 10

    subscription: Subscription
    dashboard: Dashboard
    insight: Insight
    asset: ExportedAsset
    integration: Integration

    def setUp(self) -> None:
        self.dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        self.insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")
        self.asset = ExportedAsset.objects.create(team=self.team, insight_id=self.insight.id, export_format="image/png")
        self.subscription = create_subscription(
            team=self.team,
            dashboard=self.dashboard,
            created_by=self.user,
            target_type="slack",
            target_value="C12345|#test-channel",
        )
        self.integration = Integration.objects.create(team=self.team, kind="slack")

    def test_async_delivery_all_message_success(self, MockSlackIntegration: MagicMock) -> None:
        mock_slack_integration = MagicMock()
        MockSlackIntegration.return_value = mock_slack_integration

        mock_async_client = AsyncMock()
        mock_slack_integration.async_client = MagicMock(return_value=mock_async_client)
        mock_async_client.chat_postMessage.return_value = {"ts": "1.234"}

        asset2 = ExportedAsset.objects.create(team=self.team, insight_id=self.insight.id, export_format="image/png")
        asset3 = ExportedAsset.objects.create(team=self.team, insight_id=self.insight.id, export_format="image/png")
        assets = list(
            ExportedAsset.objects.filter(id__in=[self.asset.id, asset2.id, asset3.id]).select_related("insight")
        )

        result = asyncio.run(
            send_slack_message_with_integration_async(
                self.integration, self.subscription, assets, self.TOTAL_ASSET_COUNT
            )
        )

        # Should have called chat_postMessage 4 times (1 main + 2 thread + 1 "showing X of Y")
        assert mock_async_client.chat_postMessage.call_count == 4
        assert result.is_complete_success
        assert not result.is_partial_failure
        assert result.main_message_sent
        assert len(result.failed_thread_message_indices) == 0
        assert result.total_thread_messages == 3

    @patch("products.enterprise.backend.tasks.subscriptions.slack_subscriptions.asyncio.sleep", new_callable=AsyncMock)
    def test_async_delivery_partial_success(self, mock_sleep: AsyncMock, MockSlackIntegration: MagicMock) -> None:
        """Test that thread message timeouts are retried and result in partial success."""
        mock_slack_integration = MagicMock()
        MockSlackIntegration.return_value = mock_slack_integration

        mock_async_client = AsyncMock()
        mock_slack_integration.async_client = MagicMock(return_value=mock_async_client)

        mock_async_client.chat_postMessage.side_effect = [
            {"ts": "1.234"},  # Main message
            {"ts": "2.345"},  # First thread message (asset 2)
            TimeoutError(),  # Second thread message (asset 3) attempt 1
            TimeoutError(),  # Second thread message (asset 3) attempt 2
            TimeoutError(),  # Second thread message (asset 3) attempt 3 (final failure)
            {"ts": "3.456"},  # Third thread message "Showing 3 of 10"
        ]

        asset2 = ExportedAsset.objects.create(team=self.team, insight_id=self.insight.id, export_format="image/png")
        asset3 = ExportedAsset.objects.create(team=self.team, insight_id=self.insight.id, export_format="image/png")
        assets = list(
            ExportedAsset.objects.filter(id__in=[self.asset.id, asset2.id, asset3.id]).select_related("insight")
        )

        result = asyncio.run(
            send_slack_message_with_integration_async(
                self.integration, self.subscription, assets, self.TOTAL_ASSET_COUNT
            )
        )

        assert mock_async_client.chat_postMessage.call_count == 6
        assert result.is_partial_failure
        assert not result.is_complete_success
        assert result.main_message_sent
        assert result.failed_thread_message_indices == [1]  # Second thread message (index 1)
        assert result.total_thread_messages == 3

    @patch("products.enterprise.backend.tasks.subscriptions.slack_subscriptions.asyncio.sleep", new_callable=AsyncMock)
    def test_async_delivery_main_message_timeout_raises(
        self, mock_sleep: AsyncMock, MockSlackIntegration: MagicMock
    ) -> None:
        mock_slack_integration = MagicMock()
        MockSlackIntegration.return_value = mock_slack_integration

        mock_async_client = AsyncMock()
        mock_slack_integration.async_client = MagicMock(return_value=mock_async_client)

        mock_async_client.chat_postMessage.side_effect = [
            TimeoutError(),  # Attempt 1
            TimeoutError(),  # Attempt 2
            TimeoutError(),  # Attempt 3 (final)
        ]

        assets = list(ExportedAsset.objects.filter(id=self.asset.id).select_related("insight")[:1])

        with self.assertRaises(TimeoutError):
            asyncio.run(
                send_slack_message_with_integration_async(
                    self.integration, self.subscription, assets, self.TOTAL_ASSET_COUNT
                )
            )

        assert mock_async_client.chat_postMessage.call_count == 3

    @patch("products.enterprise.backend.tasks.subscriptions.slack_subscriptions.asyncio.sleep", new_callable=AsyncMock)
    def test_async_delivery_retry_succeeds_on_second_attempt(
        self, mock_sleep: AsyncMock, MockSlackIntegration: MagicMock
    ) -> None:
        """Test that retry logic succeeds on second attempt."""
        mock_slack_integration = MagicMock()
        MockSlackIntegration.return_value = mock_slack_integration

        mock_async_client = AsyncMock()
        mock_slack_integration.async_client = MagicMock(return_value=mock_async_client)

        # Main message times out once, then succeeds
        mock_async_client.chat_postMessage.side_effect = [
            TimeoutError(),  # First attempt fails
            {"ts": "1.234"},  # Second attempt succeeds
            {"ts": "2.345"},  # First thread message "Showing 1 of 10"
        ]

        assets = list(ExportedAsset.objects.filter(id=self.asset.id).select_related("insight")[:1])

        result = asyncio.run(
            send_slack_message_with_integration_async(
                self.integration, self.subscription, assets, self.TOTAL_ASSET_COUNT
            )
        )

        assert mock_async_client.chat_postMessage.call_count == 3
        assert result.is_complete_success
        assert result.main_message_sent
