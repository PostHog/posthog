from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.signals.backend.scout_chat import SCOUT_CHAT_TEMPLATES
from products.tasks.backend.logic.services.code_usage_gate import CodeUsageStatus  # tach-ignore
from products.tasks.backend.models import Task, TaskRun


class TestScoutChatTaskAPI(APIBaseTest):
    @patch("posthoganalytics.feature_enabled", return_value=False)
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_starts_chat_task_without_desktop_access(self, mock_workflow, _mock_flag):
        # Scout chat is entitled through the generally-available Inbox: it must work with the
        # Desktop `tasks` flag off, where running the same prompt through the generic task
        # endpoints 403s. The reserved origin the server stamps is what the run gate trusts.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/projects/{self.team.id}/signals/scout/chat_tasks/",
                {"chat_type": "fleet_overview"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task = Task.objects.get(id=response.json()["task_id"])
        title, prompt = SCOUT_CHAT_TEMPLATES["fleet_overview"]
        self.assertEqual(task.origin_product, Task.OriginProduct.SIGNALS_CHAT)
        self.assertEqual(task.title, title)
        self.assertEqual(task.description, prompt)
        self.assertIsNone(task.repository)
        self.assertIsNone(task.github_integration)
        self.assertIsNone(task.github_user_integration)
        run = TaskRun.objects.get(task=task)
        self.assertEqual(run.state.get("pending_user_message"), prompt)
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.logic.services.code_usage_gate.get_posthog_code_usage")
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_over_limit_team_gets_429_and_no_task(self, mock_workflow, mock_gate):
        mock_gate.return_value = CodeUsageStatus(
            is_rate_limited=True, limit_type="burst", reset_at="2026-06-09T00:00:00Z", is_pro=False
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/signals/scout/chat_tasks/",
            {"chat_type": "recent_signals"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["code"], "usage_limit_exceeded")
        self.assertFalse(Task.objects.filter(origin_product=Task.OriginProduct.SIGNALS_CHAT).exists())
        mock_workflow.assert_not_called()

    @patch("products.signals.backend.scout_chat.SCOUT_CHAT_DAILY_ATTEMPT_CAP", 0)
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_daily_attempt_cap_creates_no_task(self, mock_workflow):
        response = self.client.post(
            f"/api/projects/{self.team.id}/signals/scout/chat_tasks/",
            {"chat_type": "recent_signals"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertFalse(Task.objects.filter(origin_product=Task.OriginProduct.SIGNALS_CHAT).exists())
        mock_workflow.assert_not_called()

    @parameterized.expand([("declined", False), ("undecided", None)])
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_ai_consent_not_approved_gets_403_and_no_task(self, _name, approval, mock_workflow):
        self.organization.is_ai_data_processing_approved = approval
        self.organization.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/signals/scout/chat_tasks/",
            {"chat_type": "fleet_overview"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Task.objects.filter(origin_product=Task.OriginProduct.SIGNALS_CHAT).exists())
        mock_workflow.assert_not_called()
