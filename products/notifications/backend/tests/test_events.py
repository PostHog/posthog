from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, Team, User

from products.notifications.backend.events import CONCIERGE_DELIVERED_EVENT, capture_notification_delivered
from products.notifications.backend.facade.contracts import NotificationData
from products.notifications.backend.facade.enums import NotificationType, Priority, TargetType
from products.notifications.backend.logic import create_notification
from products.notifications.backend.models import NotificationEvent


def _concierge_data(team: Team, target_id: str, target_type: TargetType = TargetType.USER) -> NotificationData:
    return NotificationData(
        team_id=team.id,
        notification_type=NotificationType.CONCIERGE,
        title="Hello from PostHog",
        body="A nicely-delivered scroll.",
        target_type=target_type,
        target_id=target_id,
        priority=Priority.NORMAL,
    )


class TestCaptureNotificationDelivered(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Concierge Org")
        self.team = Team.objects.create(organization=self.organization, name="Concierge Team")
        self.user = User.objects.create_and_join(self.organization, "concierge@test.com", "password")
        self.user.distinct_id = "user-distinct-1"
        self.user.save()

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    @patch("products.notifications.backend.events.get_regional_ph_client")
    def test_concierge_send_captures_one_event_per_recipient(self, mock_client_fn, _mock_publish, _mock_ff):
        user2 = User.objects.create_and_join(self.organization, "concierge2@test.com", "password")
        user2.distinct_id = "user-distinct-2"
        user2.save()

        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        with self.captureOnCommitCallbacks(execute=True):
            event = create_notification(_concierge_data(self.team, str(self.organization.id), TargetType.ORGANIZATION))

        assert event is not None
        assert mock_client.capture.call_count == 2

        captured_distinct_ids = {call.kwargs["distinct_id"] for call in mock_client.capture.call_args_list}
        assert captured_distinct_ids == {"user-distinct-1", "user-distinct-2"}

        first_call = mock_client.capture.call_args_list[0].kwargs
        assert first_call["event"] == CONCIERGE_DELIVERED_EVENT
        properties = first_call["properties"]
        assert properties["notification_id"] == str(event.id)
        assert properties["notification_type"] == "concierge"
        assert properties["priority"] == "normal"
        assert properties["title"] == "Hello from PostHog"
        assert properties["team_id"] == self.team.id
        assert properties["organization_id"] == str(self.organization.id)
        assert properties["recipient_count"] == 2

        mock_client.shutdown.assert_called_once()

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    @patch("products.notifications.backend.events.get_regional_ph_client")
    def test_non_concierge_type_does_not_capture(self, mock_client_fn, _mock_publish, _mock_ff):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.COMMENT_MENTION,
            title="Mentioned",
            body="",
            target_type=TargetType.USER,
            target_id=str(self.user.id),
        )
        with self.captureOnCommitCallbacks(execute=True):
            create_notification(data)

        mock_client.capture.assert_not_called()

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    @patch("products.notifications.backend.events.get_regional_ph_client")
    def test_users_muting_concierge_are_not_captured(self, mock_client_fn, _mock_publish, _mock_ff):
        muted = User.objects.create_and_join(self.organization, "muted@test.com", "password")
        muted.distinct_id = "muted-distinct"
        muted.partial_notification_settings = {
            "realtime_notifications_disabled": {"concierge": {str(self.team.id): True}}
        }
        muted.save()

        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        with self.captureOnCommitCallbacks(execute=True):
            create_notification(_concierge_data(self.team, str(self.organization.id), TargetType.ORGANIZATION))

        captured_distinct_ids = {call.kwargs["distinct_id"] for call in mock_client.capture.call_args_list}
        assert "muted-distinct" not in captured_distinct_ids
        assert captured_distinct_ids == {"user-distinct-1"}

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    @patch("products.notifications.backend.events.get_regional_ph_client")
    def test_capture_failure_does_not_break_delivery(self, mock_client_fn, _mock_publish, _mock_ff):
        mock_client = MagicMock()
        mock_client.capture.side_effect = RuntimeError("boom")
        mock_client_fn.return_value = mock_client

        with self.captureOnCommitCallbacks(execute=True):
            event = create_notification(_concierge_data(self.team, str(self.user.id)))

        assert event is not None
        assert NotificationEvent.objects.count() == 1
        mock_client.capture.assert_called_once()
        mock_client.shutdown.assert_called_once()

    @patch("products.notifications.backend.events.get_regional_ph_client")
    def test_capture_noops_when_no_regional_client(self, mock_client_fn):
        mock_client_fn.return_value = None

        event = NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type=NotificationType.CONCIERGE.value,
            priority=Priority.NORMAL.value,
            title="Hi",
            body="",
            target_type=TargetType.USER.value,
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
        )

        capture_notification_delivered(event)
