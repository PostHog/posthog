import json

from posthog.test.base import BaseTest
from unittest.mock import patch

from rest_framework.test import APIClient

from posthog.models import Organization, Team, User

from products.notifications.backend.models import NotificationEvent


class TestSendConciergeNotificationAPI(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Concierge Org")
        self.team = Team.objects.create(organization=self.organization, name="Concierge Team")
        self.staff_user = User.objects.create_and_join(
            self.organization, "staff@posthog.com", "password", is_staff=True
        )
        self.staff_user.current_team = self.team
        self.staff_user.save()

        self.target_user = User.objects.create_and_join(self.organization, "target@example.com", "password")
        self.target_user.current_team = self.team
        self.target_user.save()

        self.client = APIClient()
        self.client.force_authenticate(user=self.staff_user)

        self.feature_flag_patcher = patch(
            "products.notifications.backend.logic.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.feature_flag_patcher.start()

    def tearDown(self):
        self.feature_flag_patcher.stop()
        super().tearDown()

    def _url(self) -> str:
        return f"/api/environments/{self.team.id}/notifications/send_concierge/"

    def _payload(self, **overrides):
        payload = {
            "target_user_ids": [self.target_user.id],
            "title": "Hello from concierge",
            "body": "This is the body",
            "priority": "normal",
            "notification_style": "envelope",
            "skill": "",
            "long_form_wizard_text": "",
        }
        payload.update(overrides)
        return payload

    def test_non_staff_user_is_forbidden(self):
        non_staff = User.objects.create_and_join(self.organization, "regular@example.com", "password")
        non_staff.current_team = self.team
        non_staff.save()
        self.client.force_authenticate(user=non_staff)

        resp = self.client.post(self._url(), data=self._payload(), format="json")
        assert resp.status_code == 403
        assert NotificationEvent.objects.filter(notification_type="concierge").count() == 0

    def test_staff_user_sends_to_one_target(self):
        resp = self.client.post(self._url(), data=self._payload(), format="json")
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["sent"] == 1
        assert body["skipped"] == []
        assert len(body["notification_event_ids"]) == 1

        event = NotificationEvent.objects.get(id=body["notification_event_ids"][0])
        assert event.notification_type == "concierge"
        assert event.target_type == "user"
        assert event.target_id == str(self.target_user.id)
        assert event.team_id == self.target_user.current_team_id
        assert event.title == "Hello from concierge"
        assert event.priority == "normal"
        parsed_body = json.loads(event.body)
        assert parsed_body == {
            "body": "This is the body",
            "skill": "",
            "long_form_wizard_text": "",
            "notification_style": "envelope",
        }

    def test_target_without_current_team_is_skipped(self):
        self.target_user.current_team = None
        self.target_user.save()

        resp = self.client.post(self._url(), data=self._payload(), format="json")
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["sent"] == 0
        assert body["notification_event_ids"] == []
        assert body["skipped"] == [{"user_id": self.target_user.id, "reason": "user has no current team"}]
        assert NotificationEvent.objects.filter(notification_type="concierge").count() == 0

    def test_mix_of_valid_and_unknown_user_ids(self):
        missing_id = 999_999
        resp = self.client.post(
            self._url(),
            data=self._payload(target_user_ids=[self.target_user.id, missing_id]),
            format="json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["sent"] == 1
        assert {"user_id": missing_id, "reason": "user not found"} in body["skipped"]
        assert len(body["notification_event_ids"]) == 1

    def test_delivery_suppressed_by_logic_layer_is_reported_as_skipped(self):
        with patch(
            "products.notifications.backend.presentation.views.create_notification",
            return_value=None,
        ):
            resp = self.client.post(self._url(), data=self._payload(), format="json")

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["sent"] == 0
        assert body["skipped"] == [
            {
                "user_id": self.target_user.id,
                "reason": "delivery suppressed (feature flag off or user preferences)",
            }
        ]

    def test_invalid_priority_returns_400(self):
        resp = self.client.post(self._url(), data=self._payload(priority="bogus"), format="json")
        assert resp.status_code == 400
        assert resp.json()["attr"] == "priority"

    def test_invalid_notification_style_returns_400(self):
        resp = self.client.post(self._url(), data=self._payload(notification_style="spaceship"), format="json")
        assert resp.status_code == 400
        assert resp.json()["attr"] == "notification_style"

    def test_empty_target_user_ids_returns_400(self):
        resp = self.client.post(self._url(), data=self._payload(target_user_ids=[]), format="json")
        assert resp.status_code == 400
        assert resp.json()["attr"] == "target_user_ids"
