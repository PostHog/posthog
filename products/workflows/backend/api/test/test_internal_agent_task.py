from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.tasks.backend.facade import contracts
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

SECRET_HEADER = "HTTP_X_WORKFLOWS_TASKS_SECRET"
SECRET = "posthog123"  # LOCAL_DEV_INTERNAL_API_SECRET, the test/dev default


class TestInternalAgentTaskAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client.logout()  # the endpoint authenticates by shared secret, not a user session
        self.hog_flow = HogFlow.objects.create(
            team=self.team, name="wf", created_by=self.user, trigger={"type": "event"}, edges=[]
        )
        self.url = f"/api/projects/{self.team.id}/internal/workflows/agent_tasks"

    def _create_body(self, **overrides):
        body = {
            "prompt": "fix the bug",
            "distinct_id": "user-1",
            "workflow_id": str(self.hog_flow.id),
            "workflow_run_id": "run-1",
            "action_id": "action-1",
        }
        body.update(overrides)
        return body

    @parameterized.expand([("missing", {}), ("wrong", {SECRET_HEADER: "nope"})])
    def test_rejects_bad_secret(self, _name, headers):
        response = self.client.post(self.url, self._create_body(), content_type="application/json", **headers)
        assert response.status_code == 401

    @patch("products.workflows.backend.api.internal_agent_task._agent_task_step_enabled", return_value=False)
    def test_returns_403_when_flag_disabled(self, _mock_flag):
        response = self.client.post(
            self.url, self._create_body(), content_type="application/json", **{SECRET_HEADER: SECRET}
        )
        assert response.status_code == 403

    @patch("products.workflows.backend.api.internal_agent_task._agent_task_step_enabled", return_value=True)
    def test_unknown_workflow_returns_404(self, _mock_flag):
        response = self.client.post(
            self.url,
            self._create_body(workflow_id="00000000-0000-0000-0000-000000000000"),
            content_type="application/json",
            **{SECRET_HEADER: SECRET},
        )
        assert response.status_code == 404

    @patch("products.workflows.backend.api.internal_agent_task.tasks_facade")
    @patch("products.workflows.backend.api.internal_agent_task._agent_task_step_enabled", return_value=True)
    def test_replayed_create_is_idempotent(self, _mock_flag, mock_facade):
        # A previously-started run for the same (workflow_run_id, action_id) is returned, not duplicated.
        mock_facade.find_workflow_agent_task_run.return_value = contracts.TaskRunDTO(
            id="11111111-1111-1111-1111-111111111111",
            task_id="22222222-2222-2222-2222-222222222222",
            team_id=self.team.id,
            status="in_progress",
            environment="cloud",
            stage=None,
            branch=None,
            error_message=None,
            output=None,
            state={},
        )
        response = self.client.post(
            self.url, self._create_body(), content_type="application/json", **{SECRET_HEADER: SECRET}
        )
        assert response.status_code == 200
        assert response.json()["task_run_id"] == "11111111-1111-1111-1111-111111111111"
        mock_facade.create_and_run_task.assert_not_called()

    @patch("products.workflows.backend.api.internal_agent_task.tasks_facade")
    @patch("products.workflows.backend.api.internal_agent_task._agent_task_step_enabled", return_value=True)
    def test_over_the_in_flight_cap_returns_429(self, _mock_flag, mock_facade):
        mock_facade.find_workflow_agent_task_run.return_value = None
        mock_facade.count_active_workflow_task_runs.return_value = 10
        response = self.client.post(
            self.url, self._create_body(), content_type="application/json", **{SECRET_HEADER: SECRET}
        )
        assert response.status_code == 429
        mock_facade.create_and_run_task.assert_not_called()

    @patch("products.workflows.backend.api.internal_agent_task._agent_task_step_enabled", return_value=True)
    def test_creator_not_in_org_is_rejected(self, _mock_flag):
        self.hog_flow.created_by = None
        self.hog_flow.save()
        response = self.client.post(
            self.url, self._create_body(), content_type="application/json", **{SECRET_HEADER: SECRET}
        )
        assert response.status_code == 400

    def test_retrieve_non_uuid_returns_404(self):
        response = self.client.get(f"{self.url}/not-a-uuid", **{SECRET_HEADER: SECRET})
        assert response.status_code == 404
