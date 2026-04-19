import json
import time
import uuid
import asyncio
import threading
from collections.abc import Iterator
from typing import ClassVar, cast

from unittest.mock import AsyncMock, MagicMock, patch

from django.http import StreamingHttpResponse
from django.test import TestCase, override_settings

import jwt
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Integration, Organization, OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.storage import object_storage

from products.tasks.backend.models import (
    CodeInvite,
    CodeInviteRedemption,
    SandboxEnvironment,
    Task,
    TaskAutomation,
    TaskRun,
)
from products.tasks.backend.serializers import TaskAutomationSerializer
from products.tasks.backend.services.connection_token import get_sandbox_jwt_public_key
from products.tasks.backend.stream.redis_stream import (
    TaskRunRedisStream,
    get_task_run_stream_key,
    publish_task_run_stream_event,
)
from products.tasks.backend.temporal.process_task.utils import get_cached_github_user_token

# Test RSA private key for JWT tests (RS256)
TEST_RSA_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDqh94SYMFsvG4C
Co9BSGjtPr2/OxzuNGr41O4+AMkDQRd9pKO49DhTA4VzwnOvrH8y4eI9N8OQne7B
wpdoouSn4DoDAS/b3SUfij/RoFUSyZiTQoWz0H6o2Vuufiz0Hf+BzlZEVnhSQ1ru
vqSf+4l8cWgeMXaFXgdD5kQ8GjvR5uqKxvO2Env1hMJRKeOOEGgCep/0c6SkMUTX
SeC+VjypVg9+8yPxtIpOQ7XKv+7e/PA0ilqehRQh4fo9BAWjUW1+HnbtsjJAjjfv
ngzIjpajuQVyMi7G79v8OvijhLMJjJBh3TdbVIfi+RkVj/H94UUfKWRfJA0eLykA
VvTiFf0nAgMBAAECggEABkLBQWFW2IXBNAm/IEGEF408uH2l/I/mqSTaBUq1EwKq
U17RRg8y77hg2CHBP9fNf3i7NuIltNcaeA6vRwpOK1MXiVv/QJHLO2fP41Mx4jIC
gi/c7NtsfiprQaG5pnykhP0SnXlndd65bzUkpOasmWdXnbK5VL8ZV40uliInJafE
1Eo9qSYCJxHmivU/4AbiBgygOAo1QIiuuUHcx0YGknLrBaMQETuvWJGE3lxVQ30/
EuRyA3r6BwN2T0z47PZBzvCpg/C1KeoYuKSMwMyEXfl+a8NclqdROkVaenmZpvVH
0lAvFDuPrBSDmU4XJbKCEfwfHjRkiWAFaTrKntGQtQKBgQD/ILoK4U9DkJoKTYvY
9lX7dg6wNO8jGLHNufU8tHhU+QnBMH3hBXrAtIKQ1sGs+D5rq/O7o0Balmct9vwb
CQZ1EpPfa83Thsv6Skd7lWK0JF7g2vVk8kT4nY/eqkgZUWgkfdMp+OMg2drYiIE8
u+sRPTCdq4Tv5miRg0OToX2H/QKBgQDrVR2GXm6ZUyFbCy8A0kttXP1YyXqDVq7p
L4kqyUq43hmbjzIRM4YDN3EvgZvVf6eub6L/3HfKvWD/OvEhHovTvHb9jkwZ3FO+
YQllB/ccAWJs/Dw5jLAsX9O+eIe4lfwROib3vYLnDTAmrXD5VL35R5F0MsdRoxk5
lTCq1sYI8wKBgGA9ZjDIgXAJUjJkwkZb1l9/T1clALiKjjf+2AXIRkQ3lXhs5G9H
8+BRt5cPjAvFsTZIrS6xDIufhNiP/NXt96OeGG4FaqVKihOmhYSW+57cwXWs4zjr
Mx1dwnHKZlw2m0R4unlwy60OwUFBbQ8ODER6gqZXl1Qv5G5Px+Qe3Q25AoGAUl+s
wgfz9r9egZvcjBEQTeuq0pVTyP1ipET7YnqrKSK1G/p3sAW09xNFDzfy8DyK2UhC
agUl+VVoym47UTh8AVWK4R4aDUNOHOmifDbZjHf/l96CxjI0yJOSbq2J9FarsOwG
D9nKJE49eIxlayD6jnM6us27bxwEDF/odSRQlXkCgYEAxn9l/5kewWkeEA0Afe1c
Uf+mepHBLw1Pbg5GJYIZPC6e5+wRNvtFjM5J6h5LVhyb7AjKeLBTeohoBKEfUyUO
rl/ql9qDIh5lJFn3uNh7+r7tmG21Zl2pyh+O8GljjZ25mYhdiwl0uqzVZaINe2Wa
vbMnD1ZQKgL8LHgb02cbTsc=
-----END PRIVATE KEY-----"""


class BaseTaskAPITest(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]
    feature_flag_patcher: MagicMock
    mock_feature_flag: MagicMock
    client: APIClient

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.user = User.objects.create_user(email="test@example.com", first_name="Test", password="password")
        cls.organization.members.add(cls.user)
        OrganizationMembership.objects.filter(user=cls.user, organization=cls.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        # Enable tasks feature flag by default
        self.set_tasks_feature_flag(True)

    def tearDown(self):
        if hasattr(self, "feature_flag_patcher"):
            self.feature_flag_patcher.stop()
        super().tearDown()

    def set_tasks_feature_flag(self, enabled=True):
        if hasattr(self, "feature_flag_patcher"):
            self.feature_flag_patcher.stop()

        self.feature_flag_patcher = patch("posthoganalytics.feature_enabled")  # type: ignore[assignment]
        self.mock_feature_flag = self.feature_flag_patcher.start()

        def check_flag(flag_name, *_args, **_kwargs):
            if flag_name == "tasks":
                return enabled
            return False

        self.mock_feature_flag.side_effect = check_flag

    def create_task(self, title="Test Task"):
        return Task.objects.create(
            team=self.team,
            title=title,
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def create_automation(
        self,
        name="Daily PRs",
        prompt="Check my GitHub PRs",
        repository="posthog/posthog",
        team=None,
        user=None,
    ):
        task = Task.objects.create(
            team=team or self.team,
            created_by=user or self.user,
            title=name,
            description=prompt,
            origin_product=Task.OriginProduct.AUTOMATION,
            repository=repository,
        )
        return TaskAutomation.objects.create(
            task=task,
            cron_expression="0 9 * * *",
            timezone="Europe/London",
            enabled=True,
        )


class TestTaskAPI(BaseTaskAPITest):
    def test_list_tasks(self):
        self.create_task("Task 1")
        self.create_task("Task 2")

        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)
        task_titles = [t["title"] for t in data["results"]]
        self.assertIn("Task 1", task_titles)
        self.assertIn("Task 2", task_titles)

    def test_list_tasks_includes_latest_run(self):
        task1 = self.create_task("Task 1")
        task2 = self.create_task("Task 2")

        # Create runs for task1
        TaskRun.objects.create(task=task1, team=self.team, status=TaskRun.Status.QUEUED)
        run1_latest = TaskRun.objects.create(task=task1, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        # Task2 has no runs

        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)

        # Find task1 and task2 in results
        task1_data = next((t for t in data["results"] if t["id"] == str(task1.id)), None)
        task2_data = next((t for t in data["results"] if t["id"] == str(task2.id)), None)

        self.assertIsNotNone(task1_data)
        self.assertIsNotNone(task2_data)
        assert task1_data is not None  # Type narrowing
        assert task2_data is not None  # Type narrowing

        # task1 should have latest_run populated
        self.assertIn("latest_run", task1_data)
        self.assertIsNotNone(task1_data["latest_run"])
        self.assertEqual(task1_data["latest_run"]["id"], str(run1_latest.id))
        self.assertEqual(task1_data["latest_run"]["status"], "in_progress")

        # task2 should have latest_run as None
        self.assertIn("latest_run", task2_data)
        self.assertIsNone(task2_data["latest_run"])

    def test_retrieve_task(self):
        task = self.create_task("Test Task")

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["title"], "Test Task")
        self.assertEqual(data["description"], "Test Description")

    def test_retrieve_task_with_latest_run(self):
        task = self.create_task("Test Task")

        _run1 = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.QUEUED,
        )

        run2 = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
        )

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("latest_run", data)
        self.assertIsNotNone(data["latest_run"])
        self.assertEqual(data["latest_run"]["id"], str(run2.id))
        self.assertEqual(data["latest_run"]["status"], "in_progress")

    def test_retrieve_task_without_runs(self):
        task = self.create_task("Test Task")

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("latest_run", data)
        self.assertIsNone(data["latest_run"])

    def test_create_task(self):
        response = self.client.post(
            "/api/projects/@current/tasks/",
            {
                "title": "New Task",
                "description": "New Description",
                "origin_product": "user_created",
                "repository": "posthog/posthog",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["title"], "New Task")
        self.assertEqual(data["description"], "New Description")
        self.assertEqual(data["repository"], "posthog/posthog")

    def test_create_task_with_signal_report_same_team(self):
        from products.signals.backend.models import SignalReport

        report = SignalReport.objects.create(team=self.team)
        response = self.client.post(
            "/api/projects/@current/tasks/",
            {
                "title": "Signal Task",
                "description": "From a signal report",
                "origin_product": "signal_report",
                "signal_report": str(report.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["signal_report"], str(report.id))

    def test_create_task_with_signal_report_different_team_rejected(self):
        from products.signals.backend.models import SignalReport

        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        report = SignalReport.objects.create(team=other_team)
        response = self.client.post(
            "/api/projects/@current/tasks/",
            {
                "title": "Cross-team Task",
                "description": "Should be rejected",
                "origin_product": "signal_report",
                "signal_report": str(report.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_task(self):
        task = self.create_task("Original Task")

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/",
            {"title": "Updated Task"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["title"], "Updated Task")

    def test_delete_task(self):
        task = self.create_task("Task to Delete")

        response = self.client.delete(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        task.refresh_from_db()
        self.assertTrue(task.deleted)
        self.assertIsNotNone(task.deleted_at)

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_triggers_workflow(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(f"/api/projects/@current/tasks/{task.id}/run/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["id"], str(task.id))
        self.assertIn("latest_run", data)
        self.assertIsNotNone(data["latest_run"])

        latest_run = data["latest_run"]
        run_id = latest_run["id"]

        mock_workflow.assert_called_once_with(
            task_id=str(task.id),
            run_id=run_id,
            team_id=task.team.id,
            user_id=self.user.id,
        )

        self.assertEqual(latest_run["task"], str(task.id))
        self.assertEqual(latest_run["status"], "queued")
        self.assertEqual(latest_run["environment"], "cloud")

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_persists_sandbox_environment_id(self, mock_workflow):
        task = self.create_task()
        sandbox_environment = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Restricted env",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.CUSTOM,
            allowed_domains=["example.com"],
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"sandbox_environment_id": str(sandbox_environment.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        run_id = response.json()["latest_run"]["id"]
        task_run = TaskRun.objects.get(id=run_id)
        self.assertEqual(task_run.state["sandbox_environment_id"], str(sandbox_environment.id))
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_persists_pending_user_message(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"pending_user_message": "Read the attached file first"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        run_id = response.json()["latest_run"]["id"]
        task_run = TaskRun.objects.get(id=run_id)
        self.assertEqual(
            task_run.state["pending_user_message"],
            "Read the attached file first",
        )
        mock_workflow.assert_called_once()

    @parameterized.expand(
        [
            ("default",),
            ("acceptEdits",),
            ("plan",),
            ("bypassPermissions",),
        ]
    )
    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_persists_initial_permission_mode(self, mode, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"initial_permission_mode": mode, "runtime_adapter": "claude", "model": "claude-sonnet-4-6"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task_run = TaskRun.objects.get(id=response.json()["latest_run"]["id"])
        assert task_run.state["initial_permission_mode"] == mode
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_omits_initial_permission_mode_when_not_set(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(f"/api/projects/@current/tasks/{task.id}/run/")

        assert response.status_code == status.HTTP_200_OK
        task_run = TaskRun.objects.get(id=response.json()["latest_run"]["id"])
        assert "initial_permission_mode" not in (task_run.state or {})
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_rejects_invalid_initial_permission_mode(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"initial_permission_mode": "invalid_mode"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_combines_pending_user_message_and_initial_permission_mode(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "pending_user_message": "Start with this",
                "initial_permission_mode": "plan",
                "runtime_adapter": "claude",
                "model": "claude-sonnet-4-6",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task_run = TaskRun.objects.get(id=response.json()["latest_run"]["id"])
        assert task_run.state["pending_user_message"] == "Start with this"
        assert task_run.state["initial_permission_mode"] == "plan"
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_persists_pr_authorship_metadata(self, mock_workflow):
        task = self.create_task()
        github_user_token = "ghu_test_token"

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "branch": "main",
                "pr_authorship_mode": "user",
                "run_source": "manual",
                "github_user_token": github_user_token,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task_run = TaskRun.objects.get(id=response.json()["latest_run"]["id"])
        assert task_run.state["pr_authorship_mode"] == "user"
        assert task_run.state["run_source"] == "manual"
        assert task_run.state["pr_base_branch"] == "main"
        assert get_cached_github_user_token(str(task_run.id)) == github_user_token
        mock_workflow.assert_called_once()

    @parameterized.expand(
        [
            ("low",),
            ("medium",),
            ("high",),
        ]
    )
    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_persists_runtime_metadata(self, reasoning_effort, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "runtime_adapter": "codex",
                "model": "gpt-5.3-codex",
                "reasoning_effort": reasoning_effort,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        latest_run = response.json()["latest_run"]
        task_run = TaskRun.objects.get(id=latest_run["id"])
        assert task_run.state["runtime_adapter"] == "codex"
        assert task_run.state["provider"] == "openai"
        assert task_run.state["model"] == "gpt-5.3-codex"
        assert task_run.state["reasoning_effort"] == reasoning_effort
        assert latest_run["runtime_adapter"] == "codex"
        assert latest_run["provider"] == "openai"
        assert latest_run["model"] == "gpt-5.3-codex"
        assert latest_run["reasoning_effort"] == reasoning_effort
        mock_workflow.assert_called_once()

    @parameterized.expand([("auto",), ("read-only",), ("full-access",)])
    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_preserves_codex_initial_permission_mode(self, initial_permission_mode, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "runtime_adapter": "codex",
                "model": "gpt-5.4",
                "initial_permission_mode": initial_permission_mode,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task_run = TaskRun.objects.get(id=response.json()["latest_run"]["id"])
        assert task_run.state["initial_permission_mode"] == initial_permission_mode
        mock_workflow.assert_called_once()

    @parameterized.expand(
        [
            (
                "claude_rejects_codex_mode",
                "claude",
                "claude-opus-4-6",
                "auto",
                "Invalid choice 'auto' for runtime_adapter 'claude'. Supported values: 'default', 'acceptEdits', 'plan', 'bypassPermissions'.",
            ),
            (
                "codex_rejects_claude_mode",
                "codex",
                "gpt-5.4",
                "plan",
                "Invalid choice 'plan' for runtime_adapter 'codex'. Supported values: 'auto', 'read-only', 'full-access'.",
            ),
        ]
    )
    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_rejects_mismatched_permission_mode(
        self,
        _case_name,
        runtime_adapter,
        model,
        initial_permission_mode,
        expected_detail,
        mock_workflow,
    ):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "runtime_adapter": runtime_adapter,
                "model": model,
                "initial_permission_mode": initial_permission_mode,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": expected_detail,
            "attr": "initial_permission_mode",
        }
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_rejects_user_authorship_without_github_user_token(self, mock_workflow):
        task = self.create_task()
        task.repository = "posthog/posthog"
        task.save(update_fields=["repository"])

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "pr_authorship_mode": "user",
                "run_source": "manual",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "github_user_token is required for user-authored cloud runs"
        mock_workflow.assert_not_called()

    @parameterized.expand(
        [
            ("missing_runtime_adapter", {"model": "gpt-5.3-codex"}, "runtime_adapter"),
            ("missing_model", {"runtime_adapter": "codex"}, "model"),
        ]
    )
    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_rejects_incomplete_runtime_selection(self, _case_name, payload, expected_attr, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            payload,
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": "This field is required when selecting a cloud runtime.",
            "attr": expected_attr,
        }
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_rejects_unsupported_codex_reasoning_effort(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "runtime_adapter": "codex",
                "model": "gpt-5.4",
                "reasoning_effort": "max",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": (
                "Reasoning effort 'max' is not supported for runtime_adapter 'codex' "
                "and model 'gpt-5.4'. Supported values: low, medium, high."
            ),
            "attr": "reasoning_effort",
        }
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_rejects_unsupported_claude_reasoning_effort(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "runtime_adapter": "claude",
                "model": "claude-sonnet-4-5",
                "reasoning_effort": "high",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": (
                "Reasoning effort 'high' is not supported for runtime_adapter 'claude' "
                "and model 'claude-sonnet-4-5'. Supported values: none."
            ),
            "attr": "reasoning_effort",
        }
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_derives_provider_from_runtime_adapter(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "runtime_adapter": "codex",
                "model": "gpt-5.3-codex",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        latest_run = response.json()["latest_run"]
        task_run = TaskRun.objects.get(id=latest_run["id"])
        assert task_run.state["provider"] == "openai"
        assert latest_run["provider"] == "openai"
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_allows_user_authorship_without_token_when_no_repo(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "pr_authorship_mode": "user",
                "run_source": "manual",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_resume_carries_forward_pr_authorship_metadata(self, mock_workflow):
        task = self.create_task()
        github_user_token = "ghu_resume_token"
        previous_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            state={
                "pr_authorship_mode": "bot",
                "run_source": "signal_report",
                "signal_report_id": "report-123",
                "pr_base_branch": "main",
                "runtime_adapter": "codex",
                "model": "gpt-5.3-codex",
                "reasoning_effort": "medium",
                "snapshot_external_id": "snap-1",
            },
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "resume_from_run_id": str(previous_run.id),
                "pending_user_message": "Please continue",
                "github_user_token": github_user_token,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task_run = TaskRun.objects.get(id=response.json()["latest_run"]["id"])
        assert task_run.state["pr_authorship_mode"] == "bot"
        assert task_run.state["run_source"] == "signal_report"
        assert task_run.state["signal_report_id"] == "report-123"
        assert task_run.state["snapshot_external_id"] == "snap-1"
        assert task_run.state["pr_base_branch"] == "main"
        assert task_run.state["runtime_adapter"] == "codex"
        assert task_run.state["provider"] == "openai"
        assert task_run.state["model"] == "gpt-5.3-codex"
        assert task_run.state["reasoning_effort"] == "medium"
        # Token not cached for bot-authored runs even if the client sends one
        assert get_cached_github_user_token(str(task_run.id)) is None

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_resume_rejects_inherited_invalid_reasoning_effort(self, mock_workflow):
        task = self.create_task()
        previous_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            state={
                "runtime_adapter": "codex",
                "model": "gpt-5.4",
                "reasoning_effort": "max",
            },
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "resume_from_run_id": str(previous_run.id),
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": (
                "Reasoning effort 'max' is not supported for runtime_adapter 'codex' "
                "and model 'gpt-5.4'. Supported values: low, medium, high."
            ),
            "attr": "reasoning_effort",
        }
        mock_workflow.assert_not_called()

    def test_run_endpoint_rejects_invalid_sandbox_environment_id(self):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"sandbox_environment_id": "550e8400-e29b-41d4-a716-446655440000"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Invalid sandbox_environment_id")

    @parameterized.expand(
        [
            # (filter_param, filter_value, task_repos, expected_task_indices)
            ("repository", "posthog/posthog", ["posthog/posthog", "posthog/posthog-js", "other/posthog"], [0]),
            ("repository", "posthog", ["posthog/posthog", "posthog/posthog-js", "other/posthog"], [0, 2]),
            ("repository", "posthog-js", ["posthog/posthog", "posthog/posthog-js", "other/posthog-js"], [1, 2]),
            ("organization", "posthog", ["posthog/posthog", "posthog/posthog-js", "other/posthog"], [0, 1]),
            ("organization", "other", ["posthog/posthog", "other/repo1", "other/repo2"], [1, 2]),
            # Case insensitive tests
            ("repository", "PostHog/PostHog", ["posthog/posthog", "posthog/posthog-js"], [0]),
            ("repository", "PostHog", ["posthog/posthog", "other/posthog"], [0, 1]),
            ("organization", "PostHog", ["posthog/posthog", "posthog/posthog-js", "other/repo"], [0, 1]),
        ]
    )
    def test_filter_by_repository_and_organization(self, filter_param, filter_value, task_repos, expected_indices):
        tasks = []
        for i, repo in enumerate(task_repos):
            task = Task.objects.create(
                team=self.team,
                title=f"Task {i}",
                description="Description",
                origin_product=Task.OriginProduct.USER_CREATED,
                repository=repo,
            )
            tasks.append(task)

        response = self.client.get(f"/api/projects/@current/tasks/?{filter_param}={filter_value}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        task_ids = [t["id"] for t in data["results"]]
        expected_task_ids = [str(tasks[i].id) for i in expected_indices]

        self.assertEqual(len(task_ids), len(expected_task_ids))
        for expected_id in expected_task_ids:
            self.assertIn(expected_id, task_ids)

    def test_delete_task_soft_deletes(self):
        task = self.create_task("Task to delete")

        response = self.client.delete(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        task.refresh_from_db()
        self.assertTrue(task.deleted)
        self.assertIsNotNone(task.deleted_at)

    def test_deleted_tasks_not_in_list(self):
        task1 = self.create_task("Active Task")
        task2 = self.create_task("Deleted Task")
        task2.soft_delete()

        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["id"], str(task1.id))

    def test_deleted_task_not_retrievable(self):
        task = self.create_task("Deleted Task")
        task.soft_delete()

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @parameterized.expand(
        [
            ("self_user", "self", [0]),
            ("other_user", "other", [1]),
            ("no_filter", None, [0, 1, 2]),
        ]
    )
    def test_filter_by_created_by(self, _name, filter_user, expected_indices):
        other_user = User.objects.create_user(email="other@example.com", first_name="Other", password="password")
        self.organization.members.add(other_user)

        users = {"self": self.user, "other": other_user, None: None}

        tasks = [
            Task.objects.create(
                team=self.team,
                title="My Task",
                description="Description",
                origin_product=Task.OriginProduct.USER_CREATED,
                created_by=self.user,
            ),
            Task.objects.create(
                team=self.team,
                title="Other Task",
                description="Description",
                origin_product=Task.OriginProduct.USER_CREATED,
                created_by=other_user,
            ),
            Task.objects.create(
                team=self.team,
                title="No Creator Task",
                description="Description",
                origin_product=Task.OriginProduct.USER_CREATED,
                created_by=None,
            ),
        ]

        url = "/api/projects/@current/tasks/"
        if filter_user is not None:
            user = users[filter_user]
            assert user is not None
            url += f"?created_by={user.id}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        task_ids = [t["id"] for t in data["results"]]
        expected_task_ids = [str(tasks[i].id) for i in expected_indices]

        self.assertEqual(len(task_ids), len(expected_task_ids))
        for expected_id in expected_task_ids:
            self.assertIn(expected_id, task_ids)


class TestTaskInternalFilterAPI(BaseTaskAPITest):
    def setUp(self):
        super().setUp()
        self.external_task = self.create_task("External Task")
        self.internal_task = Task.objects.create(
            team=self.team,
            title="Internal Task",
            description="Internal Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            internal=True,
        )

    def test_list_excludes_internal_tasks_by_default(self):
        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        task_ids = [t["id"] for t in data["results"]]
        self.assertIn(str(self.external_task.id), task_ids)
        self.assertNotIn(str(self.internal_task.id), task_ids)

    def test_list_internal_true_shows_only_internal_tasks(self):
        response = self.client.get("/api/projects/@current/tasks/?internal=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        task_ids = [t["id"] for t in data["results"]]
        self.assertNotIn(str(self.external_task.id), task_ids)
        self.assertIn(str(self.internal_task.id), task_ids)

    def test_list_internal_false_excludes_internal_tasks(self):
        response = self.client.get("/api/projects/@current/tasks/?internal=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        task_ids = [t["id"] for t in data["results"]]
        self.assertIn(str(self.external_task.id), task_ids)
        self.assertNotIn(str(self.internal_task.id), task_ids)

    def test_internal_field_in_response(self):
        response = self.client.get(f"/api/projects/@current/tasks/{self.external_task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["internal"])

    def test_retrieve_internal_task_by_id(self):
        response = self.client.get(f"/api/projects/@current/tasks/{self.internal_task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["internal"])

    def test_internal_field_is_settable_on_create(self):
        response = self.client.post(
            "/api/projects/@current/tasks/",
            {"title": "Internal Task via API", "description": "Created as internal", "internal": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.json()["internal"])

    def test_internal_field_defaults_to_false_on_create(self):
        response = self.client.post(
            "/api/projects/@current/tasks/",
            {"title": "Normal Task", "description": "No internal flag"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.json()["internal"])


class TestTaskAutomationAPI(BaseTaskAPITest):
    @patch("products.tasks.backend.api.sync_automation_schedule")
    def test_create_automation(self, mock_sync_schedule):
        response = self.client.post(
            "/api/projects/@current/task_automations/",
            {
                "name": "Daily PRs",
                "prompt": "Check my GitHub PRs",
                "repository": "posthog/posthog",
                "cron_expression": "0 9 * * *",
                "timezone": "Europe/London",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payload = response.json()
        self.assertEqual(payload["name"], "Daily PRs")
        self.assertEqual(payload["repository"], "posthog/posthog")
        self.assertEqual(payload["cron_expression"], "0 9 * * *")
        self.assertEqual(payload["timezone"], "Europe/London")
        self.assertTrue(payload["enabled"])

        automation = TaskAutomation.objects.get(id=payload["id"])
        self.assertEqual(automation.task.title, "Daily PRs")
        self.assertEqual(automation.task.description, "Check my GitHub PRs")
        self.assertEqual(automation.task.repository, "posthog/posthog")
        self.assertEqual(automation.cron_expression, "0 9 * * *")
        mock_sync_schedule.assert_called_once_with(automation)

    def test_list_automations(self):
        automation = self.create_automation()

        response = self.client.get("/api/projects/@current/task_automations/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["id"], str(automation.id))
        self.assertEqual(payload["results"][0]["cron_expression"], "0 9 * * *")

    def test_create_automation_rejects_invalid_timezone(self):
        response = self.client.post(
            "/api/projects/@current/task_automations/",
            {
                "name": "Daily PRs",
                "prompt": "Check my GitHub PRs",
                "repository": "posthog/posthog",
                "cron_expression": "0 9 * * *",
                "timezone": "UTC+99",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "'UTC+99' is not a valid IANA timezone.",
                "attr": "timezone",
            },
        )

    def test_create_automation_rejects_invalid_cron_expression(self):
        response = self.client.post(
            "/api/projects/@current/task_automations/",
            {
                "name": "Daily PRs",
                "prompt": "Check my GitHub PRs",
                "repository": "posthog/posthog",
                "cron_expression": "not a cron",
                "timezone": "Europe/London",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Only standard 5-field cron expressions are supported "
                "(minute hour day month weekday). Example: '0 9 * * 1-5'.",
                "attr": "cron_expression",
            },
        )

    def test_create_automation_rolls_back_task_when_automation_create_fails(self):
        serializer = TaskAutomationSerializer(
            data={
                "name": "Daily PRs",
                "prompt": "Check my GitHub PRs",
                "repository": "posthog/posthog",
                "cron_expression": "0 9 * * *",
                "timezone": "Europe/London",
            },
            context={"team": self.team, "request": MagicMock(user=self.user)},
        )
        serializer.is_valid(raise_exception=True)

        with patch(
            "products.tasks.backend.serializers.TaskAutomation.objects.create",
            side_effect=RuntimeError("automation create failed"),
        ):
            with self.assertRaises(RuntimeError):
                serializer.save()

        self.assertFalse(
            Task.objects.filter(
                team=self.team,
                title="Daily PRs",
                origin_product=Task.OriginProduct.AUTOMATION,
            ).exists()
        )

    @patch("products.tasks.backend.api.sync_automation_schedule")
    def test_update_automation(self, mock_sync_schedule):
        automation = self.create_automation()

        response = self.client.patch(
            f"/api/projects/@current/task_automations/{automation.id}/",
            {
                "name": "Updated PR check",
                "cron_expression": "30 14 * * *",
                "enabled": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["name"], "Updated PR check")
        self.assertEqual(payload["cron_expression"], "30 14 * * *")
        self.assertFalse(payload["enabled"])

        automation.refresh_from_db()
        automation.task.refresh_from_db()
        self.assertEqual(automation.task.title, "Updated PR check")
        self.assertEqual(automation.cron_expression, "30 14 * * *")
        self.assertFalse(automation.enabled)
        mock_sync_schedule.assert_called_once_with(automation)

    def test_update_automation_rolls_back_automation_when_task_update_fails(self):
        automation = self.create_automation()

        serializer = TaskAutomationSerializer(
            automation,
            data={
                "name": "Updated PR check",
                "cron_expression": "30 14 * * *",
            },
            partial=True,
            context={"team": self.team, "request": MagicMock(user=self.user)},
        )
        serializer.is_valid(raise_exception=True)

        with patch.object(Task, "save", side_effect=RuntimeError("task update failed")):
            with self.assertRaises(RuntimeError):
                serializer.save()

        automation.refresh_from_db()
        automation.task.refresh_from_db()
        self.assertEqual(automation.cron_expression, "0 9 * * *")
        self.assertEqual(automation.task.title, "Daily PRs")

    @patch("products.tasks.backend.api.delete_automation_schedule")
    def test_delete_automation(self, mock_delete_schedule):
        automation = self.create_automation()

        response = self.client.delete(f"/api/projects/@current/task_automations/{automation.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        mock_delete_schedule.assert_called_once()
        self.assertFalse(TaskAutomation.objects.filter(id=automation.id).exists())

    @patch("products.tasks.backend.api.run_task_automation")
    def test_run(self, mock_run_task_automation):
        automation = self.create_automation()

        response = self.client.post(f"/api/projects/@current/task_automations/{automation.id}/run/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_run_task_automation.assert_called_once_with(str(automation.id))


class TestTaskRunAPI(BaseTaskAPITest):
    @patch("products.tasks.backend.models.TaskRun.publish_stream_state_event")
    @patch("products.tasks.backend.api.TaskRunViewSet._signal_workflow_completion")
    def test_update_run_status_publishes_stream_state_event(self, mock_signal, mock_publish_stream_state_event):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"status": "completed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_signal.assert_called_once()
        mock_publish_stream_state_event.assert_called_once()

    @patch("products.tasks.backend.api.TaskRunViewSet._signal_workflow_completion")
    def test_update_run_status_to_completed_signals_workflow(self, mock_signal):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"status": "completed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_signal.assert_called_once()
        call_args = mock_signal.call_args
        self.assertEqual(call_args[0][1], "completed")
        self.assertIsNone(call_args[0][2])

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.COMPLETED)
        self.assertIsNotNone(run.completed_at)

    @patch("products.tasks.backend.api.TaskRunViewSet._signal_workflow_completion")
    def test_update_run_status_to_failed_signals_workflow_with_error(self, mock_signal):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"status": "failed", "error_message": "Something went wrong"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_signal.assert_called_once()
        call_args = mock_signal.call_args
        self.assertEqual(call_args[0][1], "failed")
        self.assertEqual(call_args[0][2], "Something went wrong")

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.FAILED)
        self.assertEqual(run.error_message, "Something went wrong")

    @patch("products.tasks.backend.api.TaskRunViewSet._signal_workflow_completion")
    def test_update_run_status_to_cancelled_signals_workflow(self, mock_signal):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"status": "cancelled"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_signal.assert_called_once()
        call_args = mock_signal.call_args
        self.assertEqual(call_args[0][1], "cancelled")

    @patch("products.tasks.backend.api.TaskRunViewSet._signal_workflow_completion")
    def test_update_run_non_terminal_status_does_not_signal(self, mock_signal):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"status": "in_progress"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_signal.assert_not_called()

    @patch("products.tasks.backend.api.TaskRunViewSet._signal_workflow_completion")
    def test_update_run_same_terminal_status_does_not_signal(self, mock_signal):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"status": "completed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_signal.assert_not_called()

    def test_list_runs_for_task(self):
        task = self.create_task()

        run1 = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.QUEUED,
        )

        run2 = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
        )

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)
        run_ids = [r["id"] for r in data["results"]]
        self.assertIn(str(run1.id), run_ids)
        self.assertIn(str(run2.id), run_ids)

    def test_retrieve_specific_run(self):
        task = self.create_task()

        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
        )

        # Add some logs to S3
        run.append_log([{"type": "info", "message": "Test log output"}])

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["id"], str(run.id))
        self.assertEqual(data["status"], "in_progress")
        # Verify log_url is returned (S3 presigned URL)
        self.assertIn("log_url", data)
        self.assertIsNotNone(data["log_url"])
        self.assertTrue(data["log_url"].startswith("http"))

    def test_list_runs_only_returns_task_runs(self):
        task1 = self.create_task("Task 1")
        task2 = self.create_task("Task 2")

        run1 = TaskRun.objects.create(task=task1, team=self.team, status=TaskRun.Status.QUEUED)
        _run2 = TaskRun.objects.create(task=task2, team=self.team, status=TaskRun.Status.QUEUED)

        response = self.client.get(f"/api/projects/@current/tasks/{task1.id}/runs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["id"], str(run1.id))

    def test_retrieve_run_from_different_task_fails(self):
        task1 = self.create_task("Task 1")
        task2 = self.create_task("Task 2")

        run2 = TaskRun.objects.create(task=task2, team=self.team, status=TaskRun.Status.QUEUED)

        response = self.client.get(f"/api/projects/@current/tasks/{task1.id}/runs/{run2.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_append_log_entries(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/append_log/",
            {
                "entries": [
                    {"type": "info", "message": "Starting task"},
                    {"type": "progress", "message": "Step 1 complete"},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        run.refresh_from_db()

        # Verify logs are stored in S3
        assert run.log_url is not None
        log_content = object_storage.read(run.log_url)
        assert log_content is not None

        # Parse newline-delimited JSON
        log_entries = [json.loads(line) for line in log_content.strip().split("\n")]
        self.assertEqual(len(log_entries), 2)
        self.assertEqual(log_entries[0]["type"], "info")
        self.assertEqual(log_entries[0]["message"], "Starting task")
        self.assertEqual(log_entries[1]["type"], "progress")
        self.assertEqual(log_entries[1]["message"], "Step 1 complete")

    @patch("products.tasks.backend.temporal.process_task.activities.post_slack_update.post_slack_update")
    def test_set_output_with_pr_url_posts_slack_update_when_mapping_exists(self, mock_post_slack_update):
        from posthog.models.integration import Integration

        from products.slack_app.backend.models import SlackThreadTaskMapping

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        integration = Integration.objects.create(
            team=self.team, kind="slack-posthog-code", integration_id="T_SLACK", config={}
        )

        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=task,
            task_run=run,
            mentioning_slack_user_id="U123",
        )

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/set_output/",
            {"output": {"pr_url": "https://github.com/org/repo/pull/1"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_post_slack_update.assert_called_once()
        input_arg = mock_post_slack_update.call_args[0][0]
        self.assertEqual(input_arg.run_id, str(run.id))
        self.assertEqual(input_arg.slack_thread_context["integration_id"], integration.pk)
        self.assertEqual(input_arg.slack_thread_context["channel"], "C123")
        self.assertEqual(input_arg.slack_thread_context["thread_ts"], "1234.5678")

    @patch("products.tasks.backend.models.TaskRun.publish_stream_state_event")
    def test_set_output_publishes_stream_state_event(self, mock_publish_stream_state_event):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/set_output/",
            {"output": {"pr_url": "https://github.com/org/repo/pull/1"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_publish_stream_state_event.assert_called_once()

    @patch("products.tasks.backend.temporal.process_task.activities.post_slack_update.post_slack_update")
    def test_partial_update_with_pr_url_posts_slack_update_when_mapping_exists(self, mock_post_slack_update):
        from posthog.models.integration import Integration

        from products.slack_app.backend.models import SlackThreadTaskMapping

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        integration = Integration.objects.create(
            team=self.team, kind="slack-posthog-code", integration_id="T_SLACK", config={}
        )

        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=task,
            task_run=run,
            mentioning_slack_user_id="U123",
        )

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"output": {"pr_url": "https://github.com/org/repo/pull/2"}, "status": "in_progress"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_post_slack_update.assert_called_once()
        input_arg = mock_post_slack_update.call_args[0][0]
        self.assertEqual(input_arg.run_id, str(run.id))
        self.assertEqual(input_arg.slack_thread_context["integration_id"], integration.pk)

    def test_partial_update_merges_output_dict(self):
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            output={"head_branch": "posthog-code/update-readme"},
        )

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"output": {"pr_url": "https://github.com/org/repo/pull/2"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        run.refresh_from_db()
        self.assertEqual(
            run.output,
            {
                "head_branch": "posthog-code/update-readme",
                "pr_url": "https://github.com/org/repo/pull/2",
            },
        )

    @patch("products.tasks.backend.api.execute_posthog_code_agent_relay_workflow")
    def test_relay_message_enqueues_slack_relay_workflow(self, mock_execute_relay):
        from posthog.models.integration import Integration

        from products.slack_app.backend.models import SlackThreadTaskMapping

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        mock_execute_relay.return_value = "relay-1"

        integration = Integration.objects.create(
            team=self.team, kind="slack-posthog-code", integration_id="T_SLACK", config={}
        )
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=task,
            task_run=run,
            mentioning_slack_user_id="U123",
        )
        mock_execute_relay.return_value = "relay-1"

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/relay_message/",
            {"text": "Which license should I use?"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"status": "accepted", "relay_id": "relay-1"})
        mock_execute_relay.assert_called_once_with(
            run_id=str(run.id),
            text="Which license should I use?",
            delete_progress=True,
        )

    @patch("products.tasks.backend.api.execute_posthog_code_agent_relay_workflow")
    def test_relay_message_skips_when_no_slack_mapping(self, mock_execute_relay):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/relay_message/",
            {"text": "Which license should I use?"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"status": "skipped"})
        mock_execute_relay.assert_not_called()

    @patch("products.tasks.backend.api.execute_posthog_code_agent_relay_workflow")
    def test_relay_message_skips_for_terminal_run(self, mock_execute_relay):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/relay_message/",
            {"text": "Done"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"status": "skipped"})
        mock_execute_relay.assert_not_called()

    @patch("products.tasks.backend.api.execute_posthog_code_agent_relay_workflow")
    def test_relay_message_rejects_blank_text(self, mock_execute_relay):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/relay_message/",
            {"text": "   "},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_execute_relay.assert_not_called()

    @patch(
        "products.tasks.backend.api.execute_posthog_code_agent_relay_workflow", side_effect=Exception("temporal down")
    )
    def test_relay_message_returns_503_on_enqueue_failure(self, mock_execute_relay):
        from posthog.models.integration import Integration

        from products.slack_app.backend.models import SlackThreadTaskMapping

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        integration = Integration.objects.create(
            team=self.team, kind="slack-posthog-code", integration_id="T_SLACK", config={}
        )
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=task,
            task_run=run,
            mentioning_slack_user_id="U123",
        )

        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=integration,
            slack_workspace_id="T_SLACK",
            channel="C456",
            thread_ts="5678.1234",
            task=task,
            task_run=run,
            mentioning_slack_user_id="U456",
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/relay_message/",
            {"text": "hello"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("error", response.json())

    def test_append_log_to_existing_entries(self):
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
        )

        # Add first batch
        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/append_log/",
            {"entries": [{"type": "info", "message": "Initial entry"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Add second batch
        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/append_log/",
            {"entries": [{"type": "success", "message": "Task completed"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        run.refresh_from_db()

        # All logs should be stored in S3
        assert run.log_url is not None
        log_content = object_storage.read(run.log_url)
        assert log_content is not None

        # Parse newline-delimited JSON
        log_entries = [json.loads(line) for line in log_content.strip().split("\n")]
        self.assertEqual(len(log_entries), 2)
        self.assertEqual(log_entries[0]["message"], "Initial entry")
        self.assertEqual(log_entries[1]["message"], "Task completed")

    def test_append_log_empty_entries_fails(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/append_log/",
            {"entries": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.tasks.backend.models.TaskRun.heartbeat_workflow")
    def test_append_log_calls_heartbeat_workflow(self, mock_heartbeat):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/append_log/",
            {"entries": [{"type": "info", "message": "hello"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_heartbeat.assert_called_once()

    @patch("posthog.storage.object_storage.write")
    @patch("posthog.storage.object_storage.tag")
    def test_upload_artifacts(self, mock_tag, mock_write):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        payload = {
            "artifacts": [
                {
                    "name": "plan.md",
                    "type": "plan",
                    "content": "# Plan",
                    "content_type": "text/markdown",
                }
            ]
        }

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_write.assert_called_once()
        mock_tag.assert_called_once()

        run.refresh_from_db()
        self.assertEqual(len(run.artifacts), 1)
        artifact = run.artifacts[0]
        self.assertEqual(artifact["name"], "plan.md")
        self.assertEqual(artifact["type"], "plan")
        self.assertIn("storage_path", artifact)

    def test_upload_artifacts_requires_items(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/",
            {"artifacts": []},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("posthog.storage.object_storage.get_presigned_url")
    def test_presign_artifact_url(self, mock_presign):
        mock_presign.return_value = "https://example.com/artifact?sig=123"
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            artifacts=[
                {
                    "name": "plan.md",
                    "type": "plan",
                    "storage_path": "tasks/artifacts/team_1/task_2/run_3/plan.md",
                }
            ],
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/presign/",
            {"storage_path": "tasks/artifacts/team_1/task_2/run_3/plan.md"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["url"], "https://example.com/artifact?sig=123")
        self.assertIn("expires_in", response.json())

    def test_presign_artifact_not_found(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS, artifacts=[])

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/presign/",
            {"storage_path": "unknown"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_connection_token_returns_jwt(self):
        get_sandbox_jwt_public_key.cache_clear()

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/connection_token/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("token", data)

        public_key = get_sandbox_jwt_public_key()
        decoded = jwt.decode(
            data["token"],
            public_key,
            audience="posthog:sandbox_connection",
            algorithms=["RS256"],
        )

        self.assertEqual(decoded["run_id"], str(run.id))
        self.assertEqual(decoded["task_id"], str(task.id))
        self.assertEqual(decoded["team_id"], self.team.id)
        self.assertEqual(decoded["user_id"], self.user.id)
        self.assertIn("exp", decoded)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_connection_token_has_correct_expiry(self):
        get_sandbox_jwt_public_key.cache_clear()

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/connection_token/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        public_key = get_sandbox_jwt_public_key()
        decoded = jwt.decode(
            response.json()["token"],
            public_key,
            audience="posthog:sandbox_connection",
            algorithms=["RS256"],
        )

        now = time.time()
        expected_expiry = now + (24 * 60 * 60)
        self.assertAlmostEqual(decoded["exp"], expected_expiry, delta=60)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_connection_token_includes_distinct_id(self):
        get_sandbox_jwt_public_key.cache_clear()

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/connection_token/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        public_key = get_sandbox_jwt_public_key()
        decoded = jwt.decode(
            response.json()["token"],
            public_key,
            audience="posthog:sandbox_connection",
            algorithms=["RS256"],
        )

        self.assertIn("distinct_id", decoded)
        self.assertEqual(decoded["distinct_id"], self.user.distinct_id)

    def test_connection_token_cannot_access_other_team_run(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_task = Task.objects.create(
            team=other_team,
            title="Other Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        other_run = TaskRun.objects.create(task=other_task, team=other_team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(
            f"/api/projects/@current/tasks/{other_task.id}/runs/{other_run.id}/connection_token/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestTaskRunSessionLogsAPI(BaseTaskAPITest):
    """Tests for the GET .../session_logs/ endpoint that returns filtered log entries."""

    def _make_session_update_entry(self, session_update_type: str, timestamp: str, **extra) -> dict:
        """Build a log entry with session/update notification."""
        return {
            "type": "notification",
            "timestamp": timestamp,
            "notification": {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": session_update_type,
                        **extra,
                    }
                },
            },
        }

    def _make_posthog_entry(self, method: str, timestamp: str, **params) -> dict:
        """Build a log entry with a _posthog/* notification."""
        return {
            "type": "notification",
            "timestamp": timestamp,
            "notification": {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            },
        }

    def _seed_log(self, task, run, entries: list[dict]):
        """Write entries directly to S3 as JSONL (bypasses append_log filtering)."""
        content = "\n".join(json.dumps(e) for e in entries)
        object_storage.write(run.log_url, content.encode("utf-8"))

    def _events_url(self, task, run):
        return f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/session_logs/"

    def test_session_logs_returns_all_entries_unfiltered(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("user_message", "2026-01-01T00:00:01Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T00:00:02Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T00:00:03Z"),
        ]
        self._seed_log(task, run, entries)

        response = self.client.get(self._events_url(task, run))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 3)
        self.assertEqual(response["X-Total-Count"], "3")
        self.assertEqual(response["X-Filtered-Count"], "3")

    def test_session_logs_empty_log(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        # No log written to S3

        response = self.client.get(self._events_url(task, run))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 0)
        self.assertEqual(response["X-Total-Count"], "0")
        self.assertEqual(response["X-Filtered-Count"], "0")

    def test_session_logs_filter_by_event_types(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("user_message", "2026-01-01T00:00:01Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T00:00:02Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T00:00:03Z"),
            self._make_session_update_entry("tool_result", "2026-01-01T00:00:04Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T00:00:05Z"),
        ]
        self._seed_log(task, run, entries)

        response = self.client.get(self._events_url(task, run) + "?event_types=tool_call,tool_result")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(response["X-Total-Count"], "5")
        self.assertEqual(response["X-Filtered-Count"], "2")
        types = [e["notification"]["params"]["update"]["sessionUpdate"] for e in data]
        self.assertEqual(types, ["tool_call", "tool_result"])

    def test_session_logs_filter_by_exclude_types(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("user_message", "2026-01-01T00:00:01Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T00:00:02Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T00:00:03Z"),
        ]
        self._seed_log(task, run, entries)

        response = self.client.get(self._events_url(task, run) + "?exclude_types=agent_message")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(response["X-Filtered-Count"], "2")
        types = [e["notification"]["params"]["update"]["sessionUpdate"] for e in data]
        self.assertEqual(types, ["user_message", "tool_call"])

    def test_session_logs_filter_by_after_timestamp(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("user_message", "2026-01-01T10:00:00Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T10:05:00Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T10:10:00Z"),
            self._make_session_update_entry("tool_result", "2026-01-01T10:15:00Z"),
        ]
        self._seed_log(task, run, entries)

        # After the second entry — should return only the last two
        response = self.client.get(self._events_url(task, run) + "?after=2026-01-01T10:05:00Z")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(response["X-Total-Count"], "4")
        self.assertEqual(response["X-Filtered-Count"], "2")
        types = [e["notification"]["params"]["update"]["sessionUpdate"] for e in data]
        self.assertEqual(types, ["tool_call", "tool_result"])

    def test_session_logs_filter_after_handles_z_and_offset_formats(self):
        """Timestamps with Z suffix and +00:00 suffix should compare correctly."""
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("user_message", "2026-01-01T10:00:00Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T10:00:00.500Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T10:00:01Z"),
        ]
        self._seed_log(task, run, entries)

        # Use +00:00 format for the after param — should still match Z-format timestamps
        response = self.client.get(self._events_url(task, run) + "?after=2026-01-01T10:00:00%2B00:00")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 2)
        types = [e["notification"]["params"]["update"]["sessionUpdate"] for e in data]
        self.assertEqual(types, ["agent_message", "tool_call"])

    def test_session_logs_limit(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [self._make_session_update_entry("user_message", f"2026-01-01T00:00:{i:02d}Z") for i in range(10)]
        self._seed_log(task, run, entries)

        response = self.client.get(self._events_url(task, run) + "?limit=3")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 3)
        self.assertEqual(response["X-Total-Count"], "10")
        self.assertEqual(response["X-Filtered-Count"], "10")
        self.assertEqual(response["X-Matching-Count"], "10")
        self.assertEqual(response["X-Has-More"], "true")

    def test_session_logs_offset(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [self._make_session_update_entry("user_message", f"2026-01-01T00:00:{i:02d}Z") for i in range(6)]
        self._seed_log(task, run, entries)

        response = self.client.get(self._events_url(task, run) + "?limit=2&offset=2")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["timestamp"], "2026-01-01T00:00:02Z")
        self.assertEqual(data[1]["timestamp"], "2026-01-01T00:00:03Z")
        self.assertEqual(response["X-Total-Count"], "6")
        self.assertEqual(response["X-Filtered-Count"], "6")
        self.assertEqual(response["X-Matching-Count"], "6")
        self.assertEqual(response["X-Has-More"], "true")

    def test_session_logs_combined_filters(self):
        """Test after + event_types + limit together."""
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("user_message", "2026-01-01T10:00:00Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T10:01:00Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T10:02:00Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T10:03:00Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T10:04:00Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T10:05:00Z"),
        ]
        self._seed_log(task, run, entries)

        # After 10:01, only tool_call, limit 1
        response = self.client.get(
            self._events_url(task, run) + "?after=2026-01-01T10:01:00Z&event_types=tool_call&limit=1"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["timestamp"], "2026-01-01T10:03:00Z")

    def test_session_logs_posthog_method_filtering(self):
        """_posthog/* events should be filterable by their method name."""
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("user_message", "2026-01-01T00:00:01Z"),
            self._make_posthog_entry("_posthog/sdk_session", "2026-01-01T00:00:02Z", sessionId="s1"),
            self._make_posthog_entry("_posthog/session/resume", "2026-01-01T00:00:03Z", sessionId="s1"),
            self._make_session_update_entry("agent_message", "2026-01-01T00:00:04Z"),
        ]
        self._seed_log(task, run, entries)

        response = self.client.get(
            self._events_url(task, run) + "?event_types=_posthog/sdk_session,_posthog/session/resume"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 2)
        methods = [e["notification"]["method"] for e in data]
        self.assertEqual(methods, ["_posthog/sdk_session", "_posthog/session/resume"])

    def test_session_logs_server_timing_header(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [self._make_session_update_entry("user_message", "2026-01-01T00:00:01Z")]
        self._seed_log(task, run, entries)

        response = self.client.get(self._events_url(task, run))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("Server-Timing", response)
        self.assertIn("s3_read", response["Server-Timing"])
        self.assertIn("filter", response["Server-Timing"])


class TestTaskRunStreamAPI(BaseTaskAPITest):
    def _stream_url(self, task: Task, run: TaskRun, suffix: str = "") -> str:
        return f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/stream/{suffix}"

    def _mark_stream_complete(self, run: TaskRun) -> None:
        async def _mark() -> None:
            redis_stream = TaskRunRedisStream(get_task_run_stream_key(str(run.id)))
            await redis_stream.mark_complete()

        asyncio.run(_mark())

    def _read_stream_ids(self, run: TaskRun) -> list[str]:
        async def _read() -> list[str]:
            redis_stream = TaskRunRedisStream(get_task_run_stream_key(str(run.id)))
            messages = await redis_stream._redis_client.xrange(get_task_run_stream_key(str(run.id)))
            return [msg_id.decode("utf-8") if isinstance(msg_id, bytes) else msg_id for msg_id, _ in messages]

        return asyncio.run(_read())

    def _collect_sse_events(self, response) -> list[dict]:
        content = b"".join(response.streaming_content).decode("utf-8")
        events: list[dict] = []
        for block in [part.strip() for part in content.split("\n\n") if part.strip()]:
            event_name = None
            event_id = None
            data = None
            for line in block.splitlines():
                if line.startswith("event: "):
                    event_name = line[7:]
                elif line.startswith("id: "):
                    event_id = line[4:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
            events.append({"event": event_name, "id": event_id, "data": data})
        return events

    def test_stream_replays_events_with_ids(self):
        task = self.create_task()
        run = task.create_run()
        run.emit_console_event("info", "hello")
        self._mark_stream_complete(run)

        response = self.client.get(self._stream_url(task, run), HTTP_ACCEPT="text/event-stream")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        events = self._collect_sse_events(response)
        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[0]["data"]["type"], "task_run_state")
        self.assertIsNotNone(events[0]["id"])
        self.assertEqual(events[1]["data"]["notification"]["method"], "_posthog/console")

    def test_stream_resumes_from_last_event_id(self):
        task = self.create_task()
        run = task.create_run()
        run.emit_console_event("info", "first")
        run.emit_sandbox_output("stdout", "stderr", 0)
        stream_ids = self._read_stream_ids(run)
        self._mark_stream_complete(run)

        response = self.client.get(
            self._stream_url(task, run),
            HTTP_LAST_EVENT_ID=stream_ids[1],
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        events = self._collect_sse_events(response)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["data"]["notification"]["method"], "_posthog/sandbox_output")

    def test_stream_start_latest_only_yields_new_events(self):
        task = self.create_task()
        run = task.create_run()

        def publish_future_events() -> None:
            time.sleep(0.05)
            publish_task_run_stream_event(
                str(run.id),
                {
                    "type": "notification",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "notification": {
                        "jsonrpc": "2.0",
                        "method": "_posthog/console",
                        "params": {
                            "sessionId": str(run.id),
                            "level": "info",
                            "message": "late hello",
                        },
                    },
                },
            )
            self._mark_stream_complete(run)

        publisher = threading.Thread(target=publish_future_events)
        publisher.start()
        response = self.client.get(self._stream_url(task, run) + "?start=latest")
        events = self._collect_sse_events(response)
        publisher.join()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(events), 1)
        self.assertTrue(all(event["data"]["notification"]["method"] == "_posthog/console" for event in events), events)
        self.assertEqual(events[-1]["data"]["notification"]["params"]["message"], "late hello")


class TestTaskRunRedisStreamKeepalive(TestCase):
    def test_read_stream_entries_yields_keepalive_sentinel_when_idle(self):
        class StubRedis:
            def __init__(self):
                self.calls = 0

            async def xread(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return []
                return [
                    [
                        b"task-run-stream:test",
                        [
                            (
                                b"1-0",
                                {b"data": json.dumps({"type": "STREAM_STATUS", "status": "complete"}).encode("utf-8")},
                            )
                        ],
                    ]
                ]

        async def collect_items() -> list[object]:
            redis_stream = TaskRunRedisStream("task-run-stream:test")
            redis_stream._redis_client = StubRedis()
            items: list[object] = []
            # Force the idle branch immediately so the test does not wait on wall-clock time.
            async for item in redis_stream.read_stream_entries(keepalive_interval_seconds=0):
                items.append(item)
            return items

        self.assertEqual(asyncio.run(collect_items()), [None])


class TestTaskRunStreamKeepaliveAPI(BaseTaskAPITest):
    def _stream_url(self, task: Task, run: TaskRun) -> str:
        return f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/stream/"

    def test_stream_emits_keepalive_comments_while_idle(self):
        task = self.create_task()
        run = task.create_run()

        async def fake_read_stream_entries(self, *args, **kwargs):
            yield None
            yield (
                "1-0",
                {
                    "type": "notification",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "notification": {
                        "jsonrpc": "2.0",
                        "method": "_posthog/console",
                        "params": {
                            "sessionId": str(run.id),
                            "level": "info",
                            "message": "after idle gap",
                        },
                    },
                },
            )

        with (
            patch.object(TaskRunRedisStream, "wait_for_stream", new=AsyncMock(return_value=True)),
            patch.object(TaskRunRedisStream, "read_stream_entries", new=fake_read_stream_entries),
        ):
            response = cast(
                StreamingHttpResponse,
                self.client.get(self._stream_url(task, run), HTTP_ACCEPT="text/event-stream"),
            )
            content = b"".join(cast(Iterator[bytes], response.streaming_content)).decode("utf-8")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("event: keepalive", content)
        self.assertIn('"type": "keepalive"', content)
        self.assertIn("after idle gap", content)


class TestTasksAPIPermissions(BaseTaskAPITest):
    def setUp(self):
        super().setUp()
        # Create another team/org for cross-team tests
        self.other_org = Organization.objects.create(name="Other Org")
        self.other_team = Team.objects.create(organization=self.other_org, name="Other Team")
        self.other_user = User.objects.create_user(email="other@example.com", first_name="Other", password="password")
        self.other_org.members.add(self.other_user)
        OrganizationMembership.objects.filter(user=self.other_user, organization=self.other_org).update(
            level=OrganizationMembership.Level.ADMIN
        )

    def test_tasks_feature_flag_required(self):
        self.set_tasks_feature_flag(False)
        task = self.create_task()
        automation = self.create_automation(name="Daily PRs", prompt="Check my PRs")
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)

        endpoints = [
            # TaskViewSet endpoints
            ("/api/projects/@current/tasks/", "GET"),
            (f"/api/projects/@current/tasks/{task.id}/", "GET"),
            ("/api/projects/@current/tasks/", "POST"),
            (f"/api/projects/@current/tasks/{task.id}/", "PATCH"),
            (f"/api/projects/@current/tasks/{task.id}/", "DELETE"),
            (f"/api/projects/@current/tasks/{task.id}/run/", "POST"),
            # TaskAutomationViewSet endpoints
            ("/api/projects/@current/task_automations/", "GET"),
            (f"/api/projects/@current/task_automations/{automation.id}/", "GET"),
            ("/api/projects/@current/task_automations/", "POST"),
            (f"/api/projects/@current/task_automations/{automation.id}/", "PATCH"),
            (f"/api/projects/@current/task_automations/{automation.id}/", "DELETE"),
            (f"/api/projects/@current/task_automations/{automation.id}/run/", "POST"),
            # TaskRunViewSet endpoints
            (f"/api/projects/@current/tasks/{task.id}/runs/", "GET"),
            (f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/", "GET"),
            (f"/api/projects/@current/tasks/{task.id}/runs/", "POST"),
            (f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/", "PATCH"),
            (f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/set_output/", "PATCH"),
            (f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/append_log/", "POST"),
            (f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/relay_message/", "POST"),
            (f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/command/", "POST"),
        ]

        for url, method in endpoints:
            response = getattr(self.client, method.lower())(url, format="json")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, f"Failed for {method} {url}")

    def test_invite_redemption_grants_access_when_flag_disabled(self):
        self.set_tasks_feature_flag(False)
        invite = CodeInvite.objects.create(code="TESTCODE", max_redemptions=0, is_active=True)
        CodeInviteRedemption.objects.create(invite_code=invite, user=self.user)

        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_no_flag_no_redemption_blocked(self):
        self.set_tasks_feature_flag(False)

        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authentication_required(self):
        task = self.create_task()
        automation = self.create_automation(name="Daily PRs", prompt="Check my PRs")

        self.client.force_authenticate(None)

        endpoints = [
            ("/api/projects/@current/tasks/", "GET"),
            (f"/api/projects/@current/tasks/{task.id}/", "GET"),
            ("/api/projects/@current/task_automations/", "GET"),
            (f"/api/projects/@current/task_automations/{automation.id}/", "GET"),
            (f"/api/projects/@current/task_automations/{automation.id}/run/", "POST"),
        ]

        for url, method in endpoints:
            response = getattr(self.client, method.lower())(url)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, f"Failed for {method} {url}")

    def test_cross_team_task_access_forbidden(self):
        # Create task in other team
        other_task = Task.objects.create(
            team=self.other_team,
            title="Other Team Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

        # Try to access other team's task
        response = self.client.get(f"/api/projects/@current/tasks/{other_task.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Try to update other team's task
        response = self.client.patch(
            f"/api/projects/@current/tasks/{other_task.id}/", {"title": "Hacked Title"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Try to delete other team's task
        response = self.client.delete(f"/api/projects/@current/tasks/{other_task.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cross_team_automation_access_forbidden(self):
        other_automation = self.create_automation(
            name="Other Team Automation",
            prompt="Description",
            team=self.other_team,
            user=self.other_user,
        )

        response = self.client.get(f"/api/projects/@current/task_automations/{other_automation.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.patch(
            f"/api/projects/@current/task_automations/{other_automation.id}/",
            {"name": "Hacked Automation"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.delete(f"/api/projects/@current/task_automations/{other_automation.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_endpoints_only_return_team_resources(self):
        # Create resources in both teams

        my_task = self.create_task("My Task")
        my_automation = self.create_automation(name="My automation", prompt="Mine")

        other_task = Task.objects.create(
            team=self.other_team,
            title="Other Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        other_automation = self.create_automation(
            name="Other automation",
            prompt="Other",
            team=self.other_team,
            user=self.other_user,
        )

        # List tasks should only return my team's tasks
        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        task_ids = [t["id"] for t in response.json()["results"]]
        self.assertIn(str(my_task.id), task_ids)
        self.assertNotIn(str(other_task.id), task_ids)

        response = self.client.get("/api/projects/@current/task_automations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        automation_ids = [a["id"] for a in response.json()["results"]]
        self.assertIn(str(my_automation.id), automation_ids)
        self.assertNotIn(str(other_automation.id), automation_ids)

    @parameterized.expand(
        [
            ("task:read", "GET", "/api/projects/@current/tasks/", True),
            ("task:read", "GET", f"/api/projects/@current/tasks/{{task_id}}/", True),
            ("task:read", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/", True),
            ("task:read", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/{{run_id}}/", True),
            ("task:read", "GET", "/api/projects/@current/task_automations/", True),
            ("task:read", "GET", "/api/projects/@current/task_automations/{automation_id}/", True),
            ("task:read", "POST", "/api/projects/@current/tasks/", False),
            ("task:read", "PATCH", f"/api/projects/@current/tasks/{{task_id}}/", False),
            ("task:read", "DELETE", f"/api/projects/@current/tasks/{{task_id}}/", False),
            ("task:read", "POST", f"/api/projects/@current/tasks/{{task_id}}/run/", False),
            ("task:read", "POST", "/api/projects/@current/task_automations/", False),
            ("task:write", "GET", "/api/projects/@current/tasks/", True),
            ("task:write", "POST", "/api/projects/@current/tasks/", True),
            ("task:write", "PATCH", f"/api/projects/@current/tasks/{{task_id}}/", True),
            ("task:write", "DELETE", f"/api/projects/@current/tasks/{{task_id}}/", True),
            ("task:write", "POST", f"/api/projects/@current/tasks/{{task_id}}/run/", True),
            ("task:write", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/", True),
            ("task:write", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/{{run_id}}/", True),
            ("task:write", "GET", "/api/projects/@current/task_automations/", True),
            ("task:write", "GET", "/api/projects/@current/task_automations/{automation_id}/", True),
            ("task:write", "POST", "/api/projects/@current/task_automations/", True),
            ("task:write", "PATCH", "/api/projects/@current/task_automations/{automation_id}/", True),
            ("task:write", "DELETE", "/api/projects/@current/task_automations/{automation_id}/", True),
            ("task:write", "POST", "/api/projects/@current/task_automations/{automation_id}/run/", True),
            ("other_scope:read", "GET", "/api/projects/@current/tasks/", False),
            ("other_scope:write", "POST", "/api/projects/@current/tasks/", False),
            ("*", "GET", "/api/projects/@current/tasks/", True),
            ("*", "POST", "/api/projects/@current/tasks/", True),
            ("*", "POST", f"/api/projects/@current/tasks/{{task_id}}/run/", True),
            ("*", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/", True),
            ("*", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/{{run_id}}/", True),
            ("*", "GET", "/api/projects/@current/task_automations/", True),
            ("*", "GET", "/api/projects/@current/task_automations/{automation_id}/", True),
            ("*", "POST", "/api/projects/@current/task_automations/", True),
            ("*", "POST", "/api/projects/@current/task_automations/{automation_id}/run/", True),
        ]
    )
    def test_scoped_api_key_permissions(self, scope, method, url_template, should_have_access):
        task = self.create_task()
        automation = self.create_automation(name="Scoped automation", prompt="Check my PRs")
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)

        api_key_value = generate_random_token_personal()

        PersonalAPIKey.objects.create(
            user=self.user,
            label=f"Test API Key - {scope}",
            secure_value=hash_key_value(api_key_value),
            scopes=[scope],
        )

        url = url_template.format(task_id=task.id, run_id=run.id, automation_id=automation.id)

        self.client.force_authenticate(None)

        data = {}
        if method == "POST" and url == "/api/projects/@current/tasks/":
            data = {
                "title": "New Task",
                "description": "Description",
                "origin_product": Task.OriginProduct.USER_CREATED,
            }
        elif method == "POST" and url == "/api/projects/@current/task_automations/":
            data = {
                "name": "New Automation",
                "prompt": "Check my PRs",
                "repository": "posthog/posthog",
                "cron_expression": "0 9 * * *",
                "timezone": "Europe/London",
            }
        elif method == "PATCH" and "/task_automations/" in url:
            data = {"name": "Updated Automation"}
        elif method == "PATCH" and "/tasks/" in url:
            data = {"title": "Updated Task"}

        if method == "GET":
            response = self.client.get(url, headers={"authorization": f"Bearer {api_key_value}"})
        elif method == "POST":
            response = self.client.post(url, data, format="json", headers={"authorization": f"Bearer {api_key_value}"})
        elif method == "PATCH":
            response = self.client.patch(url, data, format="json", headers={"authorization": f"Bearer {api_key_value}"})
        elif method == "DELETE":
            response = self.client.delete(url, headers={"authorization": f"Bearer {api_key_value}"})
        else:
            self.fail(f"Unsupported method: {method}")

        if should_have_access:
            self.assertNotEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"Expected access but got 403 for {scope} on {method} {url}",
            )
        else:
            self.assertEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"Expected 403 but got {response.status_code} for {scope} on {method} {url}",
            )


class TestTaskRepositoryReadinessAPI(BaseTaskAPITest):
    @patch("products.tasks.backend.api.compute_repository_readiness")
    def test_repository_readiness_endpoint(self, mock_compute):
        mock_compute.return_value = {
            "repository": "posthog/posthog",
            "classification": "backend_service",
            "excluded": False,
            "coreSuggestions": {
                "state": "ready",
                "estimated": True,
                "reason": "ok",
                "evidence": {},
            },
            "replayInsights": {
                "state": "not_applicable",
                "estimated": True,
                "reason": "n/a",
                "evidence": {},
            },
            "errorInsights": {
                "state": "ready",
                "estimated": True,
                "reason": "ok",
                "evidence": {},
            },
            "overall": "ready",
            "evidenceTaskCount": 1,
            "windowDays": 7,
            "generatedAt": "2026-01-01T00:00:00+00:00",
            "cacheAgeSeconds": 0,
        }

        response = self.client.get(
            "/api/projects/@current/tasks/repository_readiness/",
            {
                "repository": "posthog/posthog",
                "window_days": "7",
                "refresh": "false",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["repository"], "posthog/posthog")
        mock_compute.assert_called_once()

    def test_repository_readiness_requires_repository(self):
        response = self.client.get("/api/projects/@current/tasks/repository_readiness/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestTaskRunCommandAPI(BaseTaskAPITest):
    def _command_url(self, task, run):
        return f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/command/"

    def _make_user_message(self, content="Hello agent", request_id="req-1"):
        return {
            "jsonrpc": "2.0",
            "method": "user_message",
            "params": {"content": content},
            "id": request_id,
        }

    def _create_run_with_sandbox(self, task, sandbox_url="http://localhost:9999", connect_token=None):
        state = {"sandbox_url": sandbox_url, "mode": "interactive"}
        if connect_token:
            state["sandbox_connect_token"] = connect_token
        return TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state=state,
        )

    def _mock_agent_response(self, mock_post, body, status_code=200):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.ok = 200 <= status_code < 300
        mock_resp.json.return_value = body
        mock_resp.text = json.dumps(body) if isinstance(body, dict) else str(body)
        mock_post.return_value = mock_resp

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_proxies_user_message(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(
            mock_post,
            {
                "jsonrpc": "2.0",
                "id": "req-1",
                "result": {"stopReason": "end_turn"},
            },
        )

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["jsonrpc"], "2.0")
        self.assertEqual(data["result"]["stopReason"], "end_turn")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        self.assertEqual(call_kwargs[1]["json"]["method"], "user_message")
        self.assertEqual(call_kwargs[1]["json"]["params"]["content"], "Hello agent")
        self.assertIn("Bearer ", call_kwargs[1]["headers"]["Authorization"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_proxies_cancel(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(
            mock_post,
            {
                "jsonrpc": "2.0",
                "id": "req-2",
                "result": {"cancelled": True},
            },
        )

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {"jsonrpc": "2.0", "method": "cancel", "id": "req-2"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["result"]["cancelled"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_proxies_close(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(
            mock_post,
            {
                "jsonrpc": "2.0",
                "id": "req-3",
                "result": {"closed": True},
            },
        )

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {"jsonrpc": "2.0", "method": "close", "id": "req-3"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["result"]["closed"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_proxies_permission_response(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(
            mock_post,
            {"jsonrpc": "2.0", "id": "req-4", "result": {"acknowledged": True}},
        )

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {
                "jsonrpc": "2.0",
                "method": "permission_response",
                "params": {"requestId": "perm-1", "optionId": "allow"},
                "id": "req-4",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["method"], "permission_response")
        self.assertEqual(call_kwargs["json"]["params"]["requestId"], "perm-1")
        self.assertEqual(call_kwargs["json"]["params"]["optionId"], "allow")

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_proxies_set_config_option(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(
            mock_post,
            {"jsonrpc": "2.0", "id": "req-5", "result": {"updated": True}},
        )

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {
                "jsonrpc": "2.0",
                "method": "set_config_option",
                "params": {"configId": "mode", "value": "plan"},
                "id": "req-5",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["method"], "set_config_option")
        self.assertEqual(call_kwargs["json"]["params"]["configId"], "mode")
        self.assertEqual(call_kwargs["json"]["params"]["value"], "plan")

    def test_command_fails_without_sandbox_url(self):
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={},
        )

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No active sandbox", response.json()["error"])

    @parameterized.expand(
        [
            ("missing_jsonrpc", {"method": "user_message", "params": {"content": "hi"}}),
            ("invalid_jsonrpc", {"jsonrpc": "1.0", "method": "user_message", "params": {"content": "hi"}}),
            ("unknown_method", {"jsonrpc": "2.0", "method": "unknown_method", "params": {}}),
            ("user_message_empty_content", {"jsonrpc": "2.0", "method": "user_message", "params": {"content": ""}}),
            ("user_message_missing_content", {"jsonrpc": "2.0", "method": "user_message", "params": {}}),
            (
                "permission_response_missing_requestId",
                {"jsonrpc": "2.0", "method": "permission_response", "params": {"optionId": "allow"}},
            ),
            (
                "permission_response_missing_optionId",
                {"jsonrpc": "2.0", "method": "permission_response", "params": {"requestId": "req-1"}},
            ),
            (
                "permission_response_empty_params",
                {"jsonrpc": "2.0", "method": "permission_response", "params": {}},
            ),
            (
                "set_config_option_missing_configId",
                {"jsonrpc": "2.0", "method": "set_config_option", "params": {"value": "plan"}},
            ),
            (
                "set_config_option_missing_value",
                {"jsonrpc": "2.0", "method": "set_config_option", "params": {"configId": "mode"}},
            ),
            (
                "set_config_option_empty_params",
                {"jsonrpc": "2.0", "method": "set_config_option", "params": {}},
            ),
        ]
    )
    def test_command_rejects_invalid_payloads(self, _name, payload):
        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_passes_modal_connect_token_as_query_param(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(
            task,
            sandbox_url="https://sandbox.modal.run",
            connect_token="modal-token-abc123",
        )

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["params"]["_modal_connect_token"], "modal-token-abc123")
        self.assertNotIn("_modal_connect_token", call_kwargs["headers"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_no_query_params_for_docker(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task, sandbox_url="http://localhost:47821")

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["params"], {})

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_returns_502_on_connection_error(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        mock_post.side_effect = __import__("requests").ConnectionError("Connection refused")

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("not reachable", response.json()["error"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_returns_504_on_timeout(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        mock_post.side_effect = __import__("requests").Timeout("Request timed out")

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        self.assertIn("timed out", response.json()["error"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_forwards_agent_server_auth_error(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(
            mock_post,
            {"error": "Missing authorization header"},
            status_code=401,
        )

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("Missing authorization header", response.json()["error"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_forwards_agent_server_no_session_error(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(
            mock_post,
            {"error": "No active session for this run"},
            status_code=400,
        )

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("No active session", response.json()["error"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_sends_jwt_with_correct_claims(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        call_kwargs = mock_post.call_args[1]
        auth_header = call_kwargs["headers"]["Authorization"]
        token = auth_header.replace("Bearer ", "")

        public_key = get_sandbox_jwt_public_key()
        decoded = jwt.decode(
            token,
            public_key,
            audience="posthog:sandbox_connection",
            algorithms=["RS256"],
        )

        self.assertEqual(decoded["run_id"], str(run.id))
        self.assertEqual(decoded["task_id"], str(task.id))
        self.assertEqual(decoded["team_id"], self.team.id)
        self.assertEqual(decoded["user_id"], self.user.id)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_posts_to_correct_url(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task, sandbox_url="http://localhost:47821")

        self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], "http://localhost:47821/command")

    def test_command_cannot_access_other_team_run(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_task = Task.objects.create(
            team=other_team,
            title="Other Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        other_run = TaskRun.objects.create(
            task=other_task,
            team=other_team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_url": "http://localhost:9999"},
        )

        response = self.client.post(
            self._command_url(other_task, other_run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_command_rejects_posthog_prefixed_methods(self):
        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {
                "jsonrpc": "2.0",
                "method": "_posthog/user_message",
                "params": {"content": "Hello via posthog prefix"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_with_trailing_slash_sandbox_url(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task, sandbox_url="http://localhost:47821/")

        self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], "http://localhost:47821/command")

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_accepts_numeric_id(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "id": 42, "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {"jsonrpc": "2.0", "method": "cancel", "id": 42},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["id"], 42)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_uses_600s_timeout(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["timeout"], 600)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_omits_params_for_cancel(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {"cancelled": True}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        self.client.post(
            self._command_url(task, run),
            {"jsonrpc": "2.0", "method": "cancel"},
            format="json",
        )

        call_kwargs = mock_post.call_args[1]
        self.assertNotIn("params", call_kwargs["json"])

    @parameterized.expand(
        [
            ("aws_metadata", "http://169.254.169.254/latest/meta-data/"),
            ("internal_service", "http://internal-api.company.com:8080"),
            ("file_scheme", "file:///etc/passwd"),
            ("ftp", "ftp://evil.com/file"),
            ("http_arbitrary", "http://evil.com/command"),
            ("https_arbitrary", "https://evil.com/command"),
            ("http_with_at_sign", "http://localhost@evil.com/"),
            ("cloud_metadata_gcp", "http://metadata.google.internal/"),
        ]
    )
    def test_command_blocks_ssrf_urls(self, _name, malicious_url):
        task = self.create_task()
        run = self._create_run_with_sandbox(task, sandbox_url=malicious_url)

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid sandbox URL", response.json()["error"])

    @parameterized.expand(
        [
            ("docker_localhost", "http://localhost:47821"),
            ("docker_127", "http://127.0.0.1:47821"),
            ("modal_run", "https://sb-abc123.modal.run"),
            ("modal_run_subdomain", "https://test-sandbox-xyz.modal.run"),
            ("modal_host", "https://sb-abc123.w.modal.host"),
            (
                "modal_host_connect_token",
                "https://a-ta-01kjnh54bc9wwbh7ydrk4yqq1d-b778iwq0t2a33tyjqdu6eyfjn.w.modal.host",
            ),
        ]
    )
    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_allows_valid_sandbox_urls(self, _name, valid_url, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task, sandbox_url=valid_url)

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_command_with_empty_state(self):
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
        )

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No active sandbox", response.json()["error"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_accepts_id_zero(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "id": 0, "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {"jsonrpc": "2.0", "method": "cancel", "id": 0},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["id"], 0)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.api.http_requests.post")
    def test_command_generic_error_does_not_leak_details(self, mock_post):
        get_sandbox_jwt_public_key.cache_clear()
        mock_post.side_effect = RuntimeError("internal DNS resolve failed for secret-host.internal:8080")

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertNotIn("secret-host", response.json()["error"])
        self.assertNotIn("DNS", response.json()["error"])
        self.assertEqual(response.json()["error"], "Failed to send command to agent server")


class TestSandboxEnvironmentAPI(BaseTaskAPITest):
    base_url = "/api/projects/@current/sandbox_environments/"

    def detail_url(self, env_id):
        return f"{self.base_url}{env_id}/"

    def test_create_environment(self):
        response = self.client.post(
            self.base_url,
            {
                "name": "My Sandbox",
                "network_access_level": "custom",
                "allowed_domains": ["api.example.com"],
                "include_default_domains": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["name"], "My Sandbox")
        self.assertEqual(data["network_access_level"], "custom")
        self.assertIn("api.example.com", data["allowed_domains"])
        self.assertIn("api.example.com", data["effective_domains"])
        self.assertIn("github.com", data["effective_domains"])

    def test_create_environment_sets_created_by(self):
        response = self.client.post(
            self.base_url,
            {"name": "Test Env", "network_access_level": "full"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        env = SandboxEnvironment.objects.get(id=response.json()["id"])
        self.assertEqual(env.created_by, self.user)
        self.assertEqual(env.team, self.team)

    def test_list_environments(self):
        SandboxEnvironment.objects.create(team=self.team, name="Env 1", created_by=self.user)
        SandboxEnvironment.objects.create(team=self.team, name="Env 2", created_by=self.user)

        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

    def test_retrieve_environment_includes_effective_domains(self):
        env = SandboxEnvironment.objects.create(
            team=self.team,
            name="Detail Env",
            network_access_level="trusted",
            created_by=self.user,
        )
        response = self.client.get(self.detail_url(env.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("effective_domains", response.json())

    def test_update_environment(self):
        env = SandboxEnvironment.objects.create(team=self.team, name="Old Name", created_by=self.user)
        response = self.client.patch(
            self.detail_url(env.id),
            {"name": "New Name", "network_access_level": "custom", "allowed_domains": ["new.example.com"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        env.refresh_from_db()
        self.assertEqual(env.name, "New Name")
        self.assertEqual(env.allowed_domains, ["new.example.com"])

    def test_delete_environment(self):
        env = SandboxEnvironment.objects.create(team=self.team, name="To Delete", created_by=self.user)
        response = self.client.delete(self.detail_url(env.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(SandboxEnvironment.objects.filter(id=env.id).exists())

    def test_private_environment_only_visible_to_creator(self):
        other_user = User.objects.create_user(email="other@example.com", first_name="Other", password="password")
        self.organization.members.add(other_user)

        SandboxEnvironment.objects.create(team=self.team, name="Private", private=True, created_by=other_user)
        SandboxEnvironment.objects.create(team=self.team, name="My Private", private=True, created_by=self.user)

        response = self.client.get(self.base_url)
        names = [e["name"] for e in response.json()["results"]]
        self.assertIn("My Private", names)
        self.assertNotIn("Private", names)

    def test_public_environment_visible_to_all(self):
        other_user = User.objects.create_user(email="other2@example.com", first_name="Other2", password="password")
        self.organization.members.add(other_user)

        SandboxEnvironment.objects.create(team=self.team, name="Public Env", private=False, created_by=other_user)

        response = self.client.get(self.base_url)
        names = [e["name"] for e in response.json()["results"]]
        self.assertIn("Public Env", names)

    def test_full_access_returns_empty_effective_domains(self):
        response = self.client.post(
            self.base_url,
            {"name": "Full", "network_access_level": "full"},
            format="json",
        )
        self.assertEqual(response.json()["effective_domains"], [])

    def test_trusted_returns_default_domains(self):
        from products.tasks.backend.constants import DEFAULT_TRUSTED_DOMAINS

        response = self.client.post(
            self.base_url,
            {"name": "Trusted", "network_access_level": "trusted"},
            format="json",
        )
        self.assertEqual(response.json()["effective_domains"], DEFAULT_TRUSTED_DOMAINS)

    def test_custom_without_defaults_returns_only_custom(self):
        response = self.client.post(
            self.base_url,
            {
                "name": "Custom Only",
                "network_access_level": "custom",
                "allowed_domains": ["only-this.com"],
                "include_default_domains": False,
            },
            format="json",
        )
        self.assertEqual(response.json()["effective_domains"], ["only-this.com"])

    def test_invalid_env_var_key_rejected(self):
        response = self.client.post(
            self.base_url,
            {
                "name": "Bad Env Vars",
                "network_access_level": "full",
                "environment_variables": {"123invalid": "value"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_environment_variables_never_returned(self):
        response = self.client.post(
            self.base_url,
            {
                "name": "Secret Env",
                "network_access_level": "full",
                "environment_variables": {"SECRET_KEY": "supersecret"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertNotIn("environment_variables", data)
        self.assertTrue(data["has_environment_variables"])

        detail = self.client.get(self.detail_url(data["id"])).json()
        self.assertNotIn("environment_variables", detail)
        self.assertTrue(detail["has_environment_variables"])

        list_data = self.client.get(self.base_url).json()
        for env in list_data["results"]:
            self.assertNotIn("environment_variables", env)

    def test_has_environment_variables_false_when_empty(self):
        response = self.client.post(
            self.base_url,
            {"name": "No Vars", "network_access_level": "full"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.json()["has_environment_variables"])

    def test_custom_with_defaults_merges_without_duplicates(self):
        response = self.client.post(
            self.base_url,
            {
                "name": "Dedup Test",
                "network_access_level": "custom",
                "allowed_domains": ["github.com", "custom.io"],
                "include_default_domains": True,
            },
            format="json",
        )
        effective = response.json()["effective_domains"]
        self.assertEqual(effective.count("github.com"), 1)
        self.assertIn("custom.io", effective)

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_task_stores_sandbox_environment_id_in_state(self, mock_workflow):
        task = self.create_task()
        task.repository = "org/repo"
        task.github_integration = Integration.objects.create(team=self.team, kind="github")
        task.save()

        env = SandboxEnvironment.objects.create(
            team=self.team, name="Test Env", network_access_level="trusted", created_by=self.user
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"mode": "background", "sandbox_environment_id": str(env.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        task_run = TaskRun.objects.filter(task=task).latest("created_at")
        self.assertEqual(task_run.state.get("sandbox_environment_id"), str(env.id))

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_task_rejects_invalid_sandbox_environment_id(self, mock_workflow):
        task = self.create_task()
        task.repository = "org/repo"
        task.github_integration = Integration.objects.create(team=self.team, kind="github")
        task.save()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"mode": "background", "sandbox_environment_id": str(uuid.uuid4())},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_task_rejects_other_team_sandbox_environment(self, mock_workflow):
        task = self.create_task()
        task.repository = "org/repo"
        task.github_integration = Integration.objects.create(team=self.team, kind="github")
        task.save()

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        env = SandboxEnvironment.objects.create(
            team=other_team, name="Other Team Env", network_access_level="full", created_by=self.user
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"mode": "background", "sandbox_environment_id": str(env.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_task_without_sandbox_environment_backward_compatible(self, mock_workflow):
        task = self.create_task()
        task.repository = "org/repo"
        task.github_integration = Integration.objects.create(team=self.team, kind="github")
        task.save()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"mode": "background"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        task_run = TaskRun.objects.filter(task=task).latest("created_at")
        self.assertNotIn("sandbox_environment_id", task_run.state)
