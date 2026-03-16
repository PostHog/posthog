from posthog.test.base import BaseTest

from rest_framework.test import APIClient

from posthog.models import Organization, Team, User

from products.notifications.backend.models import NotificationEvent, NotificationReadState


class TestNotificationsAPI(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(self.organization, "apitest@test.com", "password")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.event = NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="comment_mention",
            title="Test notification",
            body="Test body",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
        )

    def test_list_notifications(self):
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["title"] == "Test notification"
        assert resp.json()[0]["read"] is False

    def test_unread_count(self):
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/unread_count/")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_mark_read(self):
        resp = self.client.post(f"/api/environments/{self.team.id}/notifications/{self.event.id}/mark_read/")
        assert resp.status_code == 200
        assert NotificationReadState.objects.filter(notification_event=self.event, user=self.user).exists()

    def test_mark_unread(self):
        NotificationReadState.objects.create(notification_event=self.event, user=self.user)
        resp = self.client.post(f"/api/environments/{self.team.id}/notifications/{self.event.id}/mark_unread/")
        assert resp.status_code == 200
        assert not NotificationReadState.objects.filter(notification_event=self.event, user=self.user).exists()

    def test_mark_all_read(self):
        NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="alert_firing",
            title="Second",
            body="",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
        )
        resp = self.client.post(f"/api/environments/{self.team.id}/notifications/mark_all_read/")
        assert resp.status_code == 200
        assert resp.json()["updated"] == 2
        assert NotificationReadState.objects.count() == 2

    def test_other_users_notifications_not_visible(self):
        other_user = User.objects.create_and_join(self.organization, "other@test.com", "password")
        NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="comment_mention",
            title="Not for me",
            body="",
            target_type="user",
            target_id=str(other_user.id),
            resolved_user_ids=[other_user.id],
        )
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/")
        assert len(resp.json()) == 1
