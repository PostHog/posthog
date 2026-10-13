from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.utils import timezone

from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog

from products.workflows.backend.models import HogFlow

TRIGGER_ACTION = {
    "id": "trigger_node",
    "name": "trigger_1",
    "type": "trigger",
    "config": {
        "type": "event",
        "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
    },
}
EXIT_ACTION = {"id": "exit_node", "name": "exit_1", "type": "exit", "config": {}}


class TestWorkflowEmailPauseAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.flow = HogFlow.objects.create(
            team=self.team,
            name="Newsletter",
            status="active",
            trigger={"type": "event"},
            edges=[{"from": "trigger_node", "to": "exit_node", "type": "continue"}],
            actions=[TRIGGER_ACTION, EXIT_ACTION],
        )

    def _pause(self, reason: str = "Spam complaints reached 2% of the 400 emails sent in the last hour.") -> None:
        self.flow.email_sending_paused_at = timezone.now() - timedelta(hours=1)
        self.flow.email_sending_paused_reason = reason
        self.flow.save(update_fields=["email_sending_paused_at", "email_sending_paused_reason"])

    def test_resume_clears_the_pause_and_stamps_the_resume_time(self):
        self._pause()

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{self.flow.id}/resume_email_sending",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["email_sending_paused"] is False
        assert body["email_sending_paused_at"] is None
        assert body["email_sending_paused_reason"] == ""
        assert body["email_sending_resumed_at"] is not None
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is None
        assert self.flow.email_sending_paused_reason == ""
        assert self.flow.email_sending_resumed_at is not None
        assert ActivityLog.objects.filter(
            scope="HogFlow", item_id=str(self.flow.id), activity="email_sending_resumed"
        ).exists()

    def test_resume_rejects_a_workflow_that_is_not_paused(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{self.flow.id}/resume_email_sending",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        self.flow.refresh_from_db()
        assert self.flow.email_sending_resumed_at is None

    def test_a_normal_update_cannot_clear_a_pause(self):
        # The resume endpoint is the only way out of a pause. A plain PATCH that sets the fields
        # back to null would otherwise be a free bypass of the whole feature.
        self._pause(reason="Spam complaints reached 2%.")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{self.flow.id}",
            {
                "name": "Newsletter renamed",
                "email_sending_paused_at": None,
                "email_sending_paused_reason": "",
                "email_sending_resumed_at": timezone.now().isoformat(),
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        self.flow.refresh_from_db()
        assert self.flow.name == "Newsletter renamed"
        assert self.flow.email_sending_paused_at is not None
        assert self.flow.email_sending_paused_reason == "Spam complaints reached 2%."
        assert self.flow.email_sending_resumed_at is None

    def test_retrieve_exposes_the_pause_state(self):
        self._pause(reason="Spam complaints reached 2%.")

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{self.flow.id}")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["email_sending_paused_at"] is not None
        assert body["email_sending_paused_reason"] == "Spam complaints reached 2%."
