from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status
from rest_framework.response import Response

from posthog.models.integration import Integration

from products.tasks.backend.models import Task, TaskAutomation, TaskRun

TRIGGER_URL = "/api/code/ci_remediation/trigger/"
_EXECUTE = "products.tasks.backend.automation_service.execute_task_processing_workflow_for_automation"


@override_settings(CI_REMEDIATION_TRIGGER_TOKEN="secret-token")
class TestCiRemediationTriggerApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        access_patcher = patch("products.tasks.backend.automation_service.has_tasks_access", return_value=True)
        access_patcher.start()
        self.addCleanup(access_patcher.stop)
        self.github_integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="github-installation",
            config={},
            sensitive_config={},
            created_by=self.user,
        )
        self.slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="slack-workspace",
            config={},
            sensitive_config={},
            created_by=self.user,
        )
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Repair master CI",
            description="Investigate sustained master CI failures.",
            origin_product=Task.OriginProduct.AUTOMATION,
            repository="PostHog/posthog",
            github_integration=self.github_integration,
        )
        self.automation = TaskAutomation.objects.create(
            task=self.task,
            cron_expression="0 0 1 1 *",
            timezone="UTC",
            enabled=False,
        )
        self.payload = {
            "incident_id": "4fc92ced-f626-4b18-9ec3-dd3171bf8f31",
            "repository": "PostHog/posthog",
            "latest_master_sha": "a" * 40,
            "incident_started_at": "2026-07-15T12:00:00Z",
            "failing_workflows": [
                {
                    "name": "Backend CI",
                    "run_url": "https://github.com/PostHog/posthog/actions/runs/123",
                }
            ],
            "slack_channel_id": "C0AS64N6DJL",
            "slack_thread_ts": "1721044800.123456",
        }

    def post_trigger(
        self, payload: dict[str, object] | None = None, authorization: str = "Bearer secret-token"
    ) -> Response:
        with self.settings(
            CI_REMEDIATION_AUTOMATION_ID=str(self.automation.id),
            CI_REMEDIATION_SLACK_INTEGRATION_ID=self.slack_integration.id,
        ):
            return self.client.post(
                TRIGGER_URL,
                payload or self.payload,
                format="json",
                HTTP_AUTHORIZATION=authorization,
            )

    @patch(_EXECUTE)
    def test_retries_return_one_task_run_with_incident_state(self, mock_execute) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            first_response = self.post_trigger()
        with self.captureOnCommitCallbacks(execute=True):
            second_response = self.post_trigger()

        self.assertEqual(first_response.status_code, status.HTTP_202_ACCEPTED, first_response.content)
        self.assertEqual(second_response.status_code, status.HTTP_202_ACCEPTED, second_response.content)
        self.assertEqual(first_response.json(), second_response.json())
        self.assertEqual(Task.objects.filter(id=self.task.id).count(), 1)
        self.assertEqual(TaskRun.objects.filter(task=self.task).count(), 1)
        mock_execute.assert_called_once()

        task_run = TaskRun.objects.get(task=self.task)
        self.assertEqual(task_run.branch, "master")
        self.assertEqual(task_run.state["automation_trigger_workflow_id"], self.payload["incident_id"])
        self.assertEqual(task_run.state["pr_base_branch"], "master")
        self.assertEqual(task_run.state["pr_authorship_mode"], "bot")
        self.assertIs(task_run.state["auto_publish"], True)
        self.assertEqual(task_run.state["pending_user_message"], task_run.state["ci_remediation_prompt"])
        self.assertIn("verify that current master is still broken", task_run.state["ci_remediation_prompt"])
        self.assertIn("Do not rerun CI", task_run.state["ci_remediation_prompt"])
        self.assertIn("Engineering analytics", task_run.state["ci_remediation_prompt"])
        self.assertEqual(task_run.state["ci_remediation_incident"]["latest_master_sha"], "a" * 40)
        self.assertEqual(
            task_run.state["pending_dispatch"]["slack_thread_context"],
            {
                "integration_id": self.slack_integration.id,
                "channel": "C0AS64N6DJL",
                "thread_ts": "1721044800.123456",
            },
        )

    @parameterized.expand(
        [
            ("wrong_token", "Bearer wrong"),
            ("missing_token", ""),
            ("not_bearer", "secret-token"),
        ]
    )
    @patch(_EXECUTE)
    def test_invalid_authentication_is_rejected(self, _name: str, authorization: str, mock_execute) -> None:
        response = self.post_trigger(authorization=authorization)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(TaskRun.objects.filter(task=self.task).exists())
        mock_execute.assert_not_called()

    @patch(_EXECUTE)
    def test_disallowed_repository_is_rejected(self, mock_execute) -> None:
        response = self.post_trigger({**self.payload, "repository": "example/private"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(TaskRun.objects.filter(task=self.task).exists())
        mock_execute.assert_not_called()

    @patch(_EXECUTE)
    def test_caller_cannot_choose_server_side_identity(self, mock_execute) -> None:
        response = self.post_trigger({**self.payload, "team_id": 999, "automation_id": "attacker-controlled"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(TaskRun.objects.filter(task=self.task).exists())
        mock_execute.assert_not_called()

    @override_settings(DEBUG=False, TEST=False, CI_REMEDIATION_TRIGGER_TOKEN=None)
    @patch(_EXECUTE)
    def test_missing_token_fails_closed_outside_development(self, mock_execute) -> None:
        response = self.post_trigger(authorization="Bearer anything")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(TaskRun.objects.filter(task=self.task).exists())
        mock_execute.assert_not_called()

    @patch(_EXECUTE)
    def test_missing_automation_configuration_returns_503(self, mock_execute) -> None:
        with self.settings(
            CI_REMEDIATION_AUTOMATION_ID=None,
            CI_REMEDIATION_SLACK_INTEGRATION_ID=self.slack_integration.id,
        ):
            response = self.client.post(
                TRIGGER_URL,
                self.payload,
                format="json",
                HTTP_AUTHORIZATION="Bearer secret-token",
            )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(TaskRun.objects.filter(task=self.task).exists())
        mock_execute.assert_not_called()

    @patch(_EXECUTE)
    def test_missing_slack_configuration_returns_503(self, mock_execute) -> None:
        with self.settings(
            CI_REMEDIATION_AUTOMATION_ID=str(self.automation.id),
            CI_REMEDIATION_SLACK_INTEGRATION_ID=None,
        ):
            response = self.client.post(
                TRIGGER_URL,
                self.payload,
                format="json",
                HTTP_AUTHORIZATION="Bearer secret-token",
            )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(TaskRun.objects.filter(task=self.task).exists())
        mock_execute.assert_not_called()
