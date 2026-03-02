import json
import time

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

import jwt
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.storage import object_storage

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.services.connection_token import get_sandbox_jwt_public_key

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
    feature_flag_patcher: MagicMock
    mock_feature_flag: MagicMock
    client: APIClient
    user: User

    def setUp(self):
        self.client = APIClient()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="test@example.com", first_name="Test", password="password")
        self.organization.members.add(self.user)
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
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


class TestTaskRunAPI(BaseTaskAPITest):
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
        self.assertEqual(response["X-Filtered-Count"], "3")

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
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)

        endpoints = [
            # TaskViewSet endpoints
            ("/api/projects/@current/tasks/", "GET"),
            (f"/api/projects/@current/tasks/{task.id}/", "GET"),
            ("/api/projects/@current/tasks/", "POST"),
            (f"/api/projects/@current/tasks/{task.id}/", "PATCH"),
            (f"/api/projects/@current/tasks/{task.id}/", "DELETE"),
            (f"/api/projects/@current/tasks/{task.id}/run/", "POST"),
            # TaskRunViewSet endpoints
            (f"/api/projects/@current/tasks/{task.id}/runs/", "GET"),
            (f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/", "GET"),
            (f"/api/projects/@current/tasks/{task.id}/runs/", "POST"),
            (f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/", "PATCH"),
            (f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/set_output/", "PATCH"),
            (f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/append_log/", "POST"),
            (f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/command/", "POST"),
        ]

        for url, method in endpoints:
            response = getattr(self.client, method.lower())(url, format="json")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, f"Failed for {method} {url}")

    def test_authentication_required(self):
        task = self.create_task()

        self.client.force_authenticate(None)

        endpoints = [
            ("/api/projects/@current/tasks/", "GET"),
            (f"/api/projects/@current/tasks/{task.id}/", "GET"),
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

    def test_list_endpoints_only_return_team_resources(self):
        # Create resources in both teams

        my_task = self.create_task("My Task")

        other_task = Task.objects.create(
            team=self.other_team,
            title="Other Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

        # List tasks should only return my team's tasks
        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        task_ids = [t["id"] for t in response.json()["results"]]
        self.assertIn(str(my_task.id), task_ids)
        self.assertNotIn(str(other_task.id), task_ids)

    @parameterized.expand(
        [
            ("task:read", "GET", "/api/projects/@current/tasks/", True),
            ("task:read", "GET", f"/api/projects/@current/tasks/{{task_id}}/", True),
            ("task:read", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/", True),
            ("task:read", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/{{run_id}}/", True),
            ("task:read", "POST", "/api/projects/@current/tasks/", False),
            ("task:read", "PATCH", f"/api/projects/@current/tasks/{{task_id}}/", False),
            ("task:read", "DELETE", f"/api/projects/@current/tasks/{{task_id}}/", False),
            ("task:read", "POST", f"/api/projects/@current/tasks/{{task_id}}/run/", False),
            ("task:write", "GET", "/api/projects/@current/tasks/", True),
            ("task:write", "POST", "/api/projects/@current/tasks/", True),
            ("task:write", "PATCH", f"/api/projects/@current/tasks/{{task_id}}/", True),
            ("task:write", "DELETE", f"/api/projects/@current/tasks/{{task_id}}/", True),
            ("task:write", "POST", f"/api/projects/@current/tasks/{{task_id}}/run/", True),
            ("task:write", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/", True),
            ("task:write", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/{{run_id}}/", True),
            ("other_scope:read", "GET", "/api/projects/@current/tasks/", False),
            ("other_scope:write", "POST", "/api/projects/@current/tasks/", False),
            ("*", "GET", "/api/projects/@current/tasks/", True),
            ("*", "POST", "/api/projects/@current/tasks/", True),
            ("*", "POST", f"/api/projects/@current/tasks/{{task_id}}/run/", True),
            ("*", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/", True),
            ("*", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/{{run_id}}/", True),
        ]
    )
    def test_scoped_api_key_permissions(self, scope, method, url_template, should_have_access):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)

        api_key_value = generate_random_token_personal()

        PersonalAPIKey.objects.create(
            user=self.user,
            label=f"Test API Key - {scope}",
            secure_value=hash_key_value(api_key_value),
            scopes=[scope],
        )

        url = url_template.format(task_id=task.id, run_id=run.id)

        self.client.force_authenticate(None)

        data = {}
        if method == "POST" and url == "/api/projects/@current/tasks/":
            data = {
                "title": "New Task",
                "description": "Description",
                "origin_product": Task.OriginProduct.USER_CREATED,
            }
        elif method == "PATCH" and "tasks" in url:
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
