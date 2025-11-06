from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.models.dashboard import Dashboard
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.models.instance_setting import set_instance_setting
from posthog.models.subscription import Subscription
from posthog.tasks.test.utils_email_tests import mock_email_messages

from products.enterprise.backend.tasks.subscriptions.email_subscriptions import send_email_subscription_report
from products.enterprise.backend.tasks.test.subscriptions.subscriptions_test_factory import create_subscription


def mock_ee_email_messages(MockEmailMessage: MagicMock):
    return mock_email_messages(MockEmailMessage, path="ee/tasks/test/__emails__/")


@patch("ee.tasks.subscriptions.email_subscriptions.EmailMessage")
@freeze_time("2022-02-02T08:55:00.000Z")
class TestEmailSubscriptionsTasks(APIBaseTest):
    subscription: Subscription
    dashboard: Dashboard
    insight: Insight
    asset: ExportedAsset

    def setUp(self) -> None:
        self.dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        self.insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")

        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

        self.asset = ExportedAsset.objects.create(team=self.team, insight_id=self.insight.id, export_format="image/png")
        self.subscription = create_subscription(team=self.team, insight=self.insight, created_by=self.user)

    def test_subscription_delivery(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_ee_email_messages(MockEmailMessage)

        send_email_subscription_report("test1@posthog.com", self.subscription, [self.asset])

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert "is ready!" in mocked_email_messages[0].html_body
        assert f"/exporter/export-my-test-subscription.png?token=ey" in mocked_email_messages[0].html_body

    def test_new_subscription_delivery(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_ee_email_messages(MockEmailMessage)

        send_email_subscription_report(
            "test1@posthog.com",
            self.subscription,
            [self.asset],
            invite_message="My invite message",
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1

        assert f"has subscribed you" in mocked_email_messages[0].html_body
        assert "Someone subscribed you to a PostHog Insight" == mocked_email_messages[0].subject
        assert "This subscription is sent every day. The next subscription will be sent on Wednesday February 02, 2022"
        assert "My invite message" in mocked_email_messages[0].html_body

    def test_should_have_different_text_for_self(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_ee_email_messages(MockEmailMessage)

        send_email_subscription_report(
            self.user.email,
            self.subscription,
            [self.asset],
            invite_message="My invite message",
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert "You have been subscribed" in mocked_email_messages[0].html_body
        assert "You have been subscribed to a PostHog Insight" == mocked_email_messages[0].subject

    def test_sends_dashboard_subscription(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_ee_email_messages(MockEmailMessage)

        subscription = create_subscription(team=self.team, dashboard=self.dashboard, created_by=self.user)

        send_email_subscription_report(
            self.user.email,
            subscription,
            [self.asset],
            invite_message="My invite message",
            total_asset_count=10,
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert "You have been subscribed" in mocked_email_messages[0].html_body
        assert "You have been subscribed to a PostHog Dashboard" == mocked_email_messages[0].subject
        assert f"SHOWING 1 OF 10 DASHBOARD INSIGHTS" in mocked_email_messages[0].html_body
