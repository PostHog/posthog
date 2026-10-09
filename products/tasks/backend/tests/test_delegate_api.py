from unittest.mock import patch

from rest_framework import status

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.tests.test_api import BaseTaskAPITest


@patch("products.tasks.backend.presentation.views.api._is_internal_debug_team", return_value=True)
@patch("products.tasks.backend.presentation.views.api.posthoganalytics.feature_enabled", return_value=True)
class TestDelegateTaskAPI(BaseTaskAPITest):
    def setUp(self) -> None:
        super().setUp()
        self.set_tasks_feature_flag(True)

    def _delegate(self, **body: object):
        payload = {"description": "Find out why signups dropped last week and write it up.", **body}
        return self.client.post(f"/api/projects/{self.team.id}/tasks/delegate/", payload, format="json")

    @patch("products.tasks.backend.temporal.client.execute_delegate_task_workflow")
    def test_creates_a_deferred_run_and_starts_the_workflow(self, mock_workflow, _flag, _internal) -> None:
        response = self._delegate(read_only_tools=True)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        body = response.json()
        self.assertNotIn("run_error", body)
        task = Task.objects.get(id=body["id"])
        self.assertEqual(task.title, "Find out why signups dropped last week and write it up.")
        self.assertEqual(task.description, "Find out why signups dropped last week and write it up.")
        run = TaskRun.objects.get(id=body["latest_run"]["id"])
        self.assertFalse(task.title_manually_set)
        self.assertEqual(run.status, TaskRun.Status.NOT_STARTED)
        self.assertEqual(run.stage, "briefing")
        self.assertTrue(run.dispatch_is_deferred)
        self.assertEqual(run.state["pending_dispatch"]["posthog_mcp_scopes"], "read_only")
        mock_workflow.assert_called_once_with(str(run.id), read_only=True)

    @patch(
        "products.tasks.backend.temporal.client.execute_delegate_task_workflow",
        side_effect=RuntimeError("temporal down"),
    )
    def test_a_workflow_start_failure_fails_the_run_and_reports_it(self, _mock_workflow, _flag, _internal) -> None:
        response = self._delegate()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        body = response.json()
        self.assertEqual(body["run_error"], "Failed to start the delegate workflow.")
        run = TaskRun.objects.get(id=body["latest_run"]["id"])
        self.assertEqual(run.status, TaskRun.Status.FAILED)
        self.assertEqual(run.error_message, "Failed to start the delegate workflow.")

    def test_disabled_flag_refuses_before_creating_anything(self, mock_flag, _internal) -> None:
        mock_flag.return_value = False

        response = self._delegate()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Task.objects.exists())
