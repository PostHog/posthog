from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import Organization, Team, User

from products.notifications.backend.facade.contracts import NotificationData
from products.notifications.backend.facade.enums import NotificationType, Priority, TargetType
from products.notifications.backend.logic import create_notification
from products.notifications.backend.models import NotificationEvent


class TestCreateNotification(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(self.organization, "test@test.com", "password")

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_redis")
    def test_create_notification_for_user(self, mock_publish, mock_ff):
        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.COMMENT_MENTION,
            title="Test notification",
            body="Test body",
            target_type=TargetType.USER,
            target_id=str(self.user.id),
        )
        event = create_notification(data)

        assert event is not None
        assert event.resolved_user_ids == [self.user.id]
        assert event.organization_id == self.organization.id
        assert event.notification_type == "comment_mention"
        assert NotificationEvent.objects.count() == 1

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_redis")
    def test_create_notification_for_organization(self, mock_publish, mock_ff):
        user2 = User.objects.create_and_join(self.organization, "test2@test.com", "password")

        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.ALERT_FIRING,
            title="Org-wide alert",
            body="Something happened",
            target_type=TargetType.ORGANIZATION,
            target_id=str(self.organization.id),
            priority=Priority.URGENT,
        )
        event = create_notification(data)

        assert event is not None
        assert set(event.resolved_user_ids) == {self.user.id, user2.id}

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=False)
    def test_feature_flag_disabled_returns_none(self, mock_ff):
        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.COMMENT_MENTION,
            title="Test",
            body="",
            target_type=TargetType.USER,
            target_id=str(self.user.id),
        )
        event = create_notification(data)
        assert event is None
        assert NotificationEvent.objects.count() == 0
