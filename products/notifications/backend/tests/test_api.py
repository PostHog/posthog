from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import User

from products.notifications.backend.models import Notification


class TestNotificationsAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.patcher = patch(
            "posthog.permissions.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        super().tearDown()

    def _create_notification(self, **kwargs):
        defaults = {
            "recipient": self.user,
            "notification_type": "comment_mention",
            "title": "Test notification",
            "body": "Test body",
            "team": self.team,
        }
        defaults.update(kwargs)
        return Notification.objects.create(**defaults)

    def test_list_returns_only_current_users_notifications(self):
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        self._create_notification(title="My notification")
        self._create_notification(title="Other notification", recipient=other_user)

        response = self.client.get(f"/api/environments/{self.team.id}/notifications/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["title"] == "My notification"

    def test_unread_count_returns_correct_count(self):
        self._create_notification(read=False)
        self._create_notification(read=False)
        self._create_notification(read=True)

        response = self.client.get(f"/api/environments/{self.team.id}/notifications/unread_count/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 2

    def test_mark_all_read(self):
        self._create_notification(read=False)
        self._create_notification(read=False)

        response = self.client.post(f"/api/environments/{self.team.id}/notifications/mark_all_read/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["updated"] == 2
        assert Notification.objects.filter(recipient=self.user, read=False).count() == 0

    def test_mark_single_read(self):
        notification = self._create_notification(read=False)

        response = self.client.post(f"/api/environments/{self.team.id}/notifications/{notification.id}/mark_read/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["read"] is True
        notification.refresh_from_db()
        assert notification.read is True
        assert notification.read_at is not None

    def test_notifications_are_team_scoped(self):
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        Notification.objects.create(
            recipient=self.user,
            notification_type="comment_mention",
            title="Other team notification",
            body="",
            team=other_team,
        )
        self._create_notification(title="My team notification")

        response = self.client.get(f"/api/environments/{self.team.id}/notifications/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["title"] == "My team notification"

    def test_returns_403_when_feature_flag_off(self):
        self.patcher.stop()
        with patch(
            "posthog.permissions.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            response = self.client.get(f"/api/environments/{self.team.id}/notifications/")
            assert response.status_code == status.HTTP_403_FORBIDDEN
        self.patcher.start()
