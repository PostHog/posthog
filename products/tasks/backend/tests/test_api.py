import json

from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.storage import object_storage

from products.tasks.backend.models import Task, TaskRun


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
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert len(data["results"]) == 2
        task_titles = [t["title"] for t in data["results"]]
        assert "Task 1" in task_titles
        assert "Task 2" in task_titles

    def test_list_tasks_includes_latest_run(self):
        task1 = self.create_task("Task 1")
        task2 = self.create_task("Task 2")

        # Create runs for task1
        TaskRun.objects.create(task=task1, team=self.team, status=TaskRun.Status.QUEUED)
        run1_latest = TaskRun.objects.create(task=task1, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        # Task2 has no runs

        response = self.client.get("/api/projects/@current/tasks/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert len(data["results"]) == 2

        # Find task1 and task2 in results
        task1_data = next((t for t in data["results"] if t["id"] == str(task1.id)), None)
        task2_data = next((t for t in data["results"] if t["id"] == str(task2.id)), None)

        assert task1_data is not None
        assert task2_data is not None
        assert task1_data is not None  # Type narrowing
        assert task2_data is not None  # Type narrowing

        # task1 should have latest_run populated
        assert "latest_run" in task1_data
        assert task1_data["latest_run"] is not None
        assert task1_data["latest_run"]["id"] == str(run1_latest.id)
        assert task1_data["latest_run"]["status"] == "in_progress"

        # task2 should have latest_run as None
        assert "latest_run" in task2_data
        assert task2_data["latest_run"] is None

    def test_retrieve_task(self):
        task = self.create_task("Test Task")

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["title"] == "Test Task"
        assert data["description"] == "Test Description"

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
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert "latest_run" in data
        assert data["latest_run"] is not None
        assert data["latest_run"]["id"] == str(run2.id)
        assert data["latest_run"]["status"] == "in_progress"

    def test_retrieve_task_without_runs(self):
        task = self.create_task("Test Task")

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert "latest_run" in data
        assert data["latest_run"] is None

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
        assert response.status_code == status.HTTP_201_CREATED

        data = response.json()
        assert data["title"] == "New Task"
        assert data["description"] == "New Description"
        assert data["repository"] == "posthog/posthog"

    def test_update_task(self):
        task = self.create_task("Original Task")

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/",
            {"title": "Updated Task"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["title"] == "Updated Task"

    def test_delete_task(self):
        task = self.create_task("Task to Delete")

        response = self.client.delete(f"/api/projects/@current/tasks/{task.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        task.refresh_from_db()
        assert task.deleted
        assert task.deleted_at is not None

    @patch("products.tasks.backend.api.execute_task_processing_workflow")
    def test_run_endpoint_triggers_workflow(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(f"/api/projects/@current/tasks/{task.id}/run/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()

        assert data["id"] == str(task.id)
        assert "latest_run" in data
        assert data["latest_run"] is not None

        latest_run = data["latest_run"]
        run_id = latest_run["id"]

        mock_workflow.assert_called_once_with(
            task_id=str(task.id),
            run_id=run_id,
            team_id=task.team.id,
            user_id=self.user.id,
        )

        assert latest_run["task"] == str(task.id)
        assert latest_run["status"] == "queued"
        assert latest_run["environment"] == "cloud"

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
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        task_ids = [t["id"] for t in data["results"]]
        expected_task_ids = [str(tasks[i].id) for i in expected_indices]

        assert len(task_ids) == len(expected_task_ids)
        for expected_id in expected_task_ids:
            assert expected_id in task_ids

    def test_delete_task_soft_deletes(self):
        task = self.create_task("Task to delete")

        response = self.client.delete(f"/api/projects/@current/tasks/{task.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        task.refresh_from_db()
        assert task.deleted
        assert task.deleted_at is not None

    def test_deleted_tasks_not_in_list(self):
        task1 = self.create_task("Active Task")
        task2 = self.create_task("Deleted Task")
        task2.soft_delete()

        response = self.client.get("/api/projects/@current/tasks/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["id"] == str(task1.id)

    def test_deleted_task_not_retrievable(self):
        task = self.create_task("Deleted Task")
        task.soft_delete()

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

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
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        task_ids = [t["id"] for t in data["results"]]
        expected_task_ids = [str(tasks[i].id) for i in expected_indices]

        assert len(task_ids) == len(expected_task_ids)
        for expected_id in expected_task_ids:
            assert expected_id in task_ids


class TestTaskRunAPI(BaseTaskAPITest):
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
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert len(data["results"]) == 2
        run_ids = [r["id"] for r in data["results"]]
        assert str(run1.id) in run_ids
        assert str(run2.id) in run_ids

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
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["id"] == str(run.id)
        assert data["status"] == "in_progress"
        # Verify log_url is returned (S3 presigned URL)
        assert "log_url" in data
        assert data["log_url"] is not None
        assert data["log_url"].startswith("http")

    def test_list_runs_only_returns_task_runs(self):
        task1 = self.create_task("Task 1")
        task2 = self.create_task("Task 2")

        run1 = TaskRun.objects.create(task=task1, team=self.team, status=TaskRun.Status.QUEUED)
        _run2 = TaskRun.objects.create(task=task2, team=self.team, status=TaskRun.Status.QUEUED)

        response = self.client.get(f"/api/projects/@current/tasks/{task1.id}/runs/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["id"] == str(run1.id)

    def test_retrieve_run_from_different_task_fails(self):
        task1 = self.create_task("Task 1")
        task2 = self.create_task("Task 2")

        run2 = TaskRun.objects.create(task=task2, team=self.team, status=TaskRun.Status.QUEUED)

        response = self.client.get(f"/api/projects/@current/tasks/{task1.id}/runs/{run2.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

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
        assert response.status_code == status.HTTP_200_OK

        run.refresh_from_db()

        # Verify logs are stored in S3
        assert run.log_url is not None
        log_content = object_storage.read(run.log_url)
        assert log_content is not None

        # Parse newline-delimited JSON
        log_entries = [json.loads(line) for line in log_content.strip().split("\n")]
        assert len(log_entries) == 2
        assert log_entries[0]["type"] == "info"
        assert log_entries[0]["message"] == "Starting task"
        assert log_entries[1]["type"] == "progress"
        assert log_entries[1]["message"] == "Step 1 complete"

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
        assert response.status_code == status.HTTP_200_OK

        # Add second batch
        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/append_log/",
            {"entries": [{"type": "success", "message": "Task completed"}]},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        run.refresh_from_db()

        # All logs should be stored in S3
        assert run.log_url is not None
        log_content = object_storage.read(run.log_url)
        assert log_content is not None

        # Parse newline-delimited JSON
        log_entries = [json.loads(line) for line in log_content.strip().split("\n")]
        assert len(log_entries) == 2
        assert log_entries[0]["message"] == "Initial entry"
        assert log_entries[1]["message"] == "Task completed"

    def test_append_log_empty_entries_fails(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/append_log/",
            {"entries": []},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

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

        assert response.status_code == status.HTTP_200_OK
        mock_write.assert_called_once()
        mock_tag.assert_called_once()

        run.refresh_from_db()
        assert len(run.artifacts) == 1
        artifact = run.artifacts[0]
        assert artifact["name"] == "plan.md"
        assert artifact["type"] == "plan"
        assert "storage_path" in artifact

    def test_upload_artifacts_requires_items(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/",
            {"artifacts": []},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

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

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["url"] == "https://example.com/artifact?sig=123"
        assert "expires_in" in response.json()

    def test_presign_artifact_not_found(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS, artifacts=[])

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/presign/",
            {"storage_path": "unknown"},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


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
        ]

        for url, method in endpoints:
            response = getattr(self.client, method.lower())(url, format="json")
            assert response.status_code == status.HTTP_403_FORBIDDEN, f"Failed for {method} {url}"

    def test_authentication_required(self):
        task = self.create_task()

        self.client.force_authenticate(None)

        endpoints = [
            ("/api/projects/@current/tasks/", "GET"),
            (f"/api/projects/@current/tasks/{task.id}/", "GET"),
        ]

        for url, method in endpoints:
            response = getattr(self.client, method.lower())(url)
            assert response.status_code == status.HTTP_403_FORBIDDEN, f"Failed for {method} {url}"

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
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # Try to update other team's task
        response = self.client.patch(
            f"/api/projects/@current/tasks/{other_task.id}/", {"title": "Hacked Title"}, format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # Try to delete other team's task
        response = self.client.delete(f"/api/projects/@current/tasks/{other_task.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

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
        assert response.status_code == status.HTTP_200_OK
        task_ids = [t["id"] for t in response.json()["results"]]
        assert str(my_task.id) in task_ids
        assert str(other_task.id) not in task_ids

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
            assert response.status_code != status.HTTP_403_FORBIDDEN, (
                f"Expected access but got 403 for {scope} on {method} {url}"
            )
        else:
            assert response.status_code == status.HTTP_403_FORBIDDEN, (
                f"Expected 403 but got {response.status_code} for {scope} on {method} {url}"
            )
