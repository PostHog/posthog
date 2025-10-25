import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from rest_framework import status

from ...models.evaluations import Evaluation


class TestEvaluationRunViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Is this response accurate?"},
            output_type="boolean",
            output_config={},
            enabled=True,
        )

    @patch("products.llm_analytics.backend.api.evaluation_runs.sync_connect")
    def test_create_evaluation_run_success(self, mock_connect):
        """Test successfully creating an evaluation run"""
        # Mock Temporal client
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_connect.return_value = mock_client

        target_event_id = str(uuid.uuid4())

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluation_runs/",
            {
                "evaluation_id": str(self.evaluation.id),
                "target_event_id": target_event_id,
            },
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()

        assert data["status"] == "started"
        assert "workflow_id" in data
        assert data["evaluation"]["id"] == str(self.evaluation.id)
        assert data["target_event_id"] == target_event_id

        # Verify Temporal workflow was started
        mock_client.start_workflow.assert_called_once()
        call_args = mock_client.start_workflow.call_args

        assert call_args[0][0] == "run-evaluation"  # workflow name
        assert call_args[1]["task_queue"] == "general-purpose-task-queue"

    def test_create_evaluation_run_invalid_evaluation(self):
        """Test creating evaluation run with non-existent evaluation"""
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluation_runs/",
            {
                "evaluation_id": str(uuid.uuid4()),
                "target_event_id": str(uuid.uuid4()),
            },
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_evaluation_run_missing_params(self):
        """Test creating evaluation run with missing parameters"""
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluation_runs/",
            {
                "evaluation_id": str(self.evaluation.id),
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_evaluation_run_different_team(self):
        """Test creating evaluation run for evaluation from different team"""
        other_team = self.organization.teams.create(name="Other Team")
        other_evaluation = Evaluation.objects.create(
            team=other_team,
            name="Other Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test"},
            output_type="boolean",
            output_config={},
            enabled=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluation_runs/",
            {
                "evaluation_id": str(other_evaluation.id),
                "target_event_id": str(uuid.uuid4()),
            },
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
