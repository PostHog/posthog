import unittest.mock
from posthog.test.base import APIBaseTest

from django.test import override_settings

from parameterized import parameterized

from posthog.models import Team

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob

BATCH_TRIGGER = {
    "type": "batch",
    "filters": {"properties": [{"key": "$browser", "type": "person", "value": ["Chrome"], "operator": "exact"}]},
}

# The post_save signal on HogFlowBatchJob dispatches an HTTP call to the CDP service; patch it out for tests.
DISPATCH_PATH = (
    "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
)


@override_settings(INTERNAL_API_SECRET="test-secret")
class TestInternalUpdateBatchJobStatus(APIBaseTest):
    def _create_batch_job(self, status=HogFlowBatchJob.State.QUEUED):
        hog_flow = HogFlow.objects.create(
            team=self.team,
            name="Test Workflow",
            status="active",
            trigger=BATCH_TRIGGER,
            actions=[],
        )
        with unittest.mock.patch(DISPATCH_PATH):
            return HogFlowBatchJob.objects.create(team=self.team, hog_flow=hog_flow, status=status)

    def _url(self, team_id, batch_job_id):
        return f"/api/projects/{team_id}/internal/hog_flows/batch_jobs/{batch_job_id}/status"

    def _post(self, team_id, batch_job_id, body, secret="test-secret"):
        headers = {"x-internal-api-secret": secret} if secret else {}
        return self.client.post(
            self._url(team_id, batch_job_id), body, content_type="application/json", headers=headers
        )

    @parameterized.expand(["active", "completed", "failed", "cancelled"])
    def test_updates_status(self, new_status):
        batch_job = self._create_batch_job()

        response = self._post(self.team.id, batch_job.id, {"status": new_status})

        assert response.status_code == 200
        assert response.json()["status"] == new_status
        batch_job.refresh_from_db()
        assert batch_job.status == new_status

    def test_rejects_invalid_status(self):
        batch_job = self._create_batch_job()

        response = self._post(self.team.id, batch_job.id, {"status": "not-a-status"})

        assert response.status_code == 400
        batch_job.refresh_from_db()
        assert batch_job.status == HogFlowBatchJob.State.QUEUED

    def test_returns_404_for_unknown_batch_job(self):
        response = self._post(self.team.id, "01900000-0000-0000-0000-000000000000", {"status": "active"})

        assert response.status_code == 404

    def test_returns_404_for_malformed_batch_job_id(self):
        response = self._post(self.team.id, "not-a-uuid", {"status": "active"})

        assert response.status_code == 404

    def test_does_not_regress_a_terminal_status(self):
        batch_job = self._create_batch_job(status=HogFlowBatchJob.State.COMPLETED)

        response = self._post(self.team.id, batch_job.id, {"status": "active"})

        assert response.status_code == 200
        assert response.json()["status"] == HogFlowBatchJob.State.COMPLETED
        batch_job.refresh_from_db()
        assert batch_job.status == HogFlowBatchJob.State.COMPLETED

    def test_requires_internal_api_secret(self):
        batch_job = self._create_batch_job()

        response = self._post(self.team.id, batch_job.id, {"status": "active"}, secret=None)

        assert response.status_code in (401, 403)
        batch_job.refresh_from_db()
        assert batch_job.status == HogFlowBatchJob.State.QUEUED

    def test_does_not_update_batch_job_scoped_to_another_team(self):
        batch_job = self._create_batch_job()
        other_team = Team.objects.create(organization=self.organization, name="Other team")

        # Another team must not be able to update a batch job it doesn't own.
        response = self._post(other_team.id, batch_job.id, {"status": "active"})

        assert response.status_code == 404
        batch_job.refresh_from_db()
        assert batch_job.status == HogFlowBatchJob.State.QUEUED
