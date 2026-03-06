from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.notifications.backend.facade.api import NotificationData, create_notification
from products.notifications.backend.facade.enums import NotificationType, Priority
from products.notifications.backend.models import Notification


class TestCreateNotification(APIBaseTest):
    @parameterized.expand(
        [
            ("normal_notification", NotificationType.COMMENT_MENTION, Priority.NORMAL),
            ("urgent_notification", NotificationType.ALERT_FIRING, Priority.URGENT),
            ("pipeline_failure", NotificationType.PIPELINE_FAILURE, Priority.NORMAL),
        ]
    )
    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_redis")
    def test_creates_notification_with_correct_fields(self, _name, notification_type, priority, mock_redis, mock_ff):
        data = NotificationData(
            recipient_id=self.user.id,
            notification_type=notification_type,
            priority=priority,
            title="Test title",
            body="Test body",
            team_id=self.team.id,
            source_type="Test",
            source_id="123",
            source_url="/test/123",
            actor_id=self.user.id,
        )
        result = create_notification(data)

        assert result is not None
        assert result.notification_type == notification_type.value
        assert result.priority == priority.value
        assert result.title == "Test title"
        assert result.body == "Test body"
        assert result.recipient_id == self.user.id
        assert result.team_id == self.team.id
        assert Notification.objects.count() == 1

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=False)
    def test_returns_none_when_feature_flag_off(self, mock_ff):
        data = NotificationData(
            recipient_id=self.user.id,
            notification_type=NotificationType.COMMENT_MENTION,
            title="Test",
            body="Test",
            team_id=self.team.id,
        )
        result = create_notification(data)

        assert result is None
        assert Notification.objects.count() == 0

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_redis")
    def test_returns_none_for_nonexistent_recipient(self, mock_redis, mock_ff):
        data = NotificationData(
            recipient_id=999999,
            notification_type=NotificationType.COMMENT_MENTION,
            title="Test",
            body="Test",
            team_id=self.team.id,
        )
        result = create_notification(data)

        assert result is None
        assert Notification.objects.count() == 0

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._get_redis_client")
    def test_redis_publish_called_with_correct_channel(self, mock_get_client, mock_ff):
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        mock_get_client.return_value = mock_client

        data = NotificationData(
            recipient_id=self.user.id,
            notification_type=NotificationType.COMMENT_MENTION,
            title="Test",
            body="Test",
            team_id=self.team.id,
        )
        create_notification(data)

        expected_channel = f"notifications:{self.team.id}:{self.user.id}"
        expected_buffer_key = f"notification_buffer:{self.team.id}:{self.user.id}"
        mock_pipe.publish.assert_called_once()
        assert mock_pipe.publish.call_args[0][0] == expected_channel
        mock_pipe.lpush.assert_called_once()
        assert mock_pipe.lpush.call_args[0][0] == expected_buffer_key
        mock_pipe.ltrim.assert_called_once_with(expected_buffer_key, 0, 49)
        mock_pipe.execute.assert_called_once()
