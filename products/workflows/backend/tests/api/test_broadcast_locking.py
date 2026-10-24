from typing import Any
from unittest.mock import patch
from rest_framework import status

from posthog.test.base import APIBaseTest
from products.workflows.backend.models import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob

TRIGGER = {"id": "trigger_node", "name": "Audience", "type": "trigger", "config": {"type": "batch", "filters": {}}}
EMAIL = {"id": "email_node", "name": "Email", "type": "function_email", "config": {"inputs": {"email": {"value": {"to": {"email": "test@example.com"}}}}}}
EXIT = {"id": "exit_node", "name": "Exit", "type": "exit", "config": {}}
EDGES = [
    {"from": "trigger_node", "to": "email_node", "type": "continue"},
    {"from": "email_node", "to": "exit_node", "type": "continue"},
]


class TestBroadcastLockingAPI(APIBaseTest):
    def _broadcast(self, **overrides: Any) -> HogFlow:
        fields: dict[str, Any] = {
            "team": self.team,
            "name": "Product Announcement",
            "status": "draft",
            "origin_product": "broadcasts",
            "exit_condition": "exit_only_at_end",
            "trigger": TRIGGER["config"],
            "actions": [TRIGGER, EMAIL, EXIT],
            "edges": EDGES,
            **overrides,
        }
        return HogFlow.objects.create(**fields)

    def _batch_job(self, flow: HogFlow, job_status: str = "completed") -> HogFlowBatchJob:
        return HogFlowBatchJob.objects.create(
            team=self.team,
            hog_flow=flow,
            status=job_status,
            filters=flow.trigger.get("filters", {}),
            created_by=self.user,
        )

    def test_draft_broadcast_can_be_edited(self) -> None:
        flow = self._broadcast(status="draft")
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow.id}/",
            {"name": "Updated Draft Name", "actions": [TRIGGER, EMAIL, EXIT]},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        flow.refresh_from_db()
        assert flow.name == "Updated Draft Name"

    def test_sent_broadcast_content_edits_are_locked(self) -> None:
        flow = self._broadcast(status="active")
        self._batch_job(flow, job_status="completed")

        # Attempt to edit content (actions)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow.id}/",
            {"actions": [TRIGGER, EXIT]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "Broadcasts are locked once sent or sending" in str(response.json())

    def test_sent_broadcast_cannot_be_moved_back_to_draft(self) -> None:
        flow = self._broadcast(status="active")
        self._batch_job(flow, job_status="completed")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow.id}/",
            {"status": "draft"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "Broadcasts are locked once sent or sending" in str(response.json())

    def test_sent_broadcast_cannot_be_dispatched_again(self) -> None:
        flow = self._broadcast(status="active")
        self._batch_job(flow, job_status="completed")

        with patch("products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.dispatch_batch_job"):
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/{flow.id}/batch_jobs/",
                {},
                format="json",
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "This broadcast has already been sent or is sending" in str(response.json())

    def test_sent_broadcast_can_be_archived(self) -> None:
        flow = self._broadcast(status="active")
        self._batch_job(flow, job_status="completed")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow.id}/",
            {"status": "archived"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        flow.refresh_from_db()
        assert flow.status == "archived"

    def test_regular_workflow_is_not_locked_after_batch_job(self) -> None:
        # Workflows without origin_product='broadcasts' legitimately evolve
        flow = self._broadcast(origin_product=None, status="active")
        self._batch_job(flow, job_status="completed")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow.id}/",
            {"name": "Evolved Workflow Name"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        flow.refresh_from_db()
        assert flow.name == "Evolved Workflow Name"
