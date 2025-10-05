from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal

from products.tasks.backend.lib.templates import DEFAULT_WORKFLOW_TEMPLATE
from products.tasks.backend.models import Task, TaskProgress, TaskWorkflow, WorkflowStage


class BaseTaskAPITest(TestCase):
    feature_flag_patcher: MagicMock
    mock_feature_flag: MagicMock
    client: APIClient

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

    def create_workflow(self, name="Test Workflow", is_default=False, is_active=True):
        workflow = TaskWorkflow.objects.create(
            team=self.team,
            name=name,
            description="Test Description",
            is_default=is_default,
            is_active=is_active,
        )
        self.create_workflow_stages(workflow)
        return workflow

    def create_workflow_stages(self, workflow):
        return [
            WorkflowStage.objects.create(
                workflow=workflow,
                name="Backlog",
                key="backlog",
                position=0,
                color="#6b7280",
            ),
            WorkflowStage.objects.create(
                workflow=workflow,
                name="In Progress",
                key="in_progress",
                position=1,
                color="#3b82f6",
            ),
            WorkflowStage.objects.create(
                workflow=workflow,
                name="Done",
                key="done",
                position=2,
                color="#10b981",
            ),
        ]

    def create_task(self, title="Test Task", workflow=None, stage=None):
        if not workflow:
            workflow = self.create_workflow()
        if not stage:
            stage = workflow.stages.first()

        return Task.objects.create(
            team=self.team,
            title=title,
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=workflow,
            current_stage=stage,
            position=0,
        )


class TestTaskWorkflowAPI(BaseTaskAPITest):
    def test_list_workflows(self):
        self.create_workflow("Workflow 1")
        self.create_workflow("Workflow 2")
        self.create_workflow("Inactive", is_active=False)

        response = self.client.get("/api/projects/@current/workflows/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)
        workflow_names = [w["name"] for w in data["results"]]
        self.assertIn("Workflow 1", workflow_names)
        self.assertIn("Workflow 2", workflow_names)
        self.assertNotIn("Inactive", workflow_names)

    def test_retrieve_workflow(self):
        workflow = self.create_workflow()

        response = self.client.get(f"/api/projects/@current/workflows/{workflow.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["name"], "Test Workflow")
        self.assertEqual(data["description"], "Test Description")
        self.assertEqual(len(data["stages"]), 3)

    def test_create_workflow(self):
        response = self.client.post(
            "/api/projects/@current/workflows/",
            {
                "name": "New Workflow",
                "description": "New Description",
                "is_default": False,
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["name"], "New Workflow")
        self.assertEqual(data["description"], "New Description")
        self.assertFalse(data["is_default"])
        self.assertTrue(data["is_active"])

    def test_update_workflow(self):
        workflow = self.create_workflow()

        response = self.client.patch(
            f"/api/projects/@current/workflows/{workflow.id}/",
            {"name": "Updated Workflow"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Updated Workflow")

    def test_delete_workflow(self):
        workflow = self.create_workflow()

        response = self.client.delete(f"/api/projects/@current/workflows/{workflow.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(TaskWorkflow.objects.filter(id=workflow.id).exists())

    def test_set_default_workflow(self):
        workflow1 = self.create_workflow("Workflow 1", is_default=True)
        workflow2 = self.create_workflow("Workflow 2", is_default=False)

        response = self.client.post(f"/api/projects/@current/workflows/{workflow2.id}/set_default/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        workflow1.refresh_from_db()
        workflow2.refresh_from_db()
        self.assertFalse(workflow1.is_default)
        self.assertTrue(workflow2.is_default)

    def test_deactivate_workflow(self):
        workflow = self.create_workflow()

        response = self.client.post(f"/api/projects/@current/workflows/{workflow.id}/deactivate/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        workflow.refresh_from_db()
        self.assertFalse(workflow.is_active)

    def test_deactivate_default_workflow_fails(self):
        workflow = self.create_workflow(is_default=True)

        response = self.client.post(f"/api/projects/@current/workflows/{workflow.id}/deactivate/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "Cannot deactivate the default workflow")

    def test_create_default_workflow(self):
        response = self.client.post("/api/projects/@current/workflows/create_default/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["name"], DEFAULT_WORKFLOW_TEMPLATE.name)
        self.assertTrue(data["is_default"])

    def test_create_default_workflow_when_exists_fails(self):
        self.create_workflow(is_default=True)

        response = self.client.post("/api/projects/@current/workflows/create_default/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "Team already has a default workflow")

    def test_permission_denied_without_auth(self):
        self.client.force_authenticate(None)
        response = self.client.get("/api/projects/@current/workflows/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_feature_flag_required(self):
        self.set_tasks_feature_flag(False)
        response = self.client.get("/api/projects/@current/workflows/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestWorkflowStageAPI(BaseTaskAPITest):
    def test_list_stages(self):
        workflow = self.create_workflow()
        WorkflowStage.objects.create(
            workflow=workflow,
            name="Archived",
            key="archived",
            position=99,
            is_archived=True,
        )

        response = self.client.get(f"/api/projects/@current/workflows/{workflow.id}/stages/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 3)
        stage_names = [s["name"] for s in data["results"]]
        self.assertNotIn("Archived", stage_names)

    def test_retrieve_stage(self):
        workflow = self.create_workflow()
        stage = workflow.stages.first()

        response = self.client.get(f"/api/projects/@current/workflows/{workflow.id}/stages/{stage.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["name"], "Backlog")
        self.assertEqual(data["key"], "backlog")

    def test_create_stage(self):
        workflow = self.create_workflow()

        response = self.client.post(
            f"/api/projects/@current/workflows/{workflow.id}/stages/",
            {
                "workflow": str(workflow.id),
                "name": "New Stage",
                "key": "new_stage",
                "position": 10,
                "color": "#ff0000",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["name"], "New Stage")
        self.assertEqual(data["key"], "new_stage")

    def test_archive_stage(self):
        workflow = self.create_workflow()
        stage = workflow.stages.first()

        response = self.client.post(f"/api/projects/@current/workflows/{workflow.id}/stages/{stage.id}/archive/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        stage.refresh_from_db()
        self.assertTrue(stage.is_archived)


class TestTaskAPI(BaseTaskAPITest):
    def test_list_tasks(self):
        workflow = self.create_workflow()
        self.create_task("Task 1", workflow=workflow)
        self.create_task("Task 2", workflow=workflow)

        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)
        task_titles = [t["title"] for t in data["results"]]
        self.assertIn("Task 1", task_titles)
        self.assertIn("Task 2", task_titles)

    def test_retrieve_task(self):
        task = self.create_task("Test Task")

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["title"], "Test Task")
        self.assertEqual(data["description"], "Test Description")

    def test_create_task(self):
        workflow = self.create_workflow()
        stage = workflow.stages.first()

        response = self.client.post(
            "/api/projects/@current/tasks/",
            {
                "title": "New Task",
                "description": "New Description",
                "origin_product": "user_created",
                "workflow": str(workflow.id),
                "current_stage": str(stage.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["title"], "New Task")
        self.assertEqual(data["description"], "New Description")

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

        self.assertFalse(Task.objects.filter(id=task.id).exists())

    def test_update_stage(self):
        workflow = self.create_workflow()
        task = self.create_task(workflow=workflow)
        new_stage = workflow.stages.last()

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/update_stage/",
            {"current_stage": str(new_stage.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        task.refresh_from_db()
        self.assertEqual(task.current_stage, new_stage)

    def test_update_position(self):
        task = self.create_task()

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/update_position/",
            {"position": 5},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        task.refresh_from_db()
        self.assertEqual(task.position, 5)

    def test_bulk_reorder(self):
        workflow = self.create_workflow()
        stages = list(workflow.stages.all())
        task1 = self.create_task(title="Task 1", workflow=workflow, stage=stages[0])
        task2 = self.create_task(title="Task 2", workflow=workflow, stage=stages[0])

        response = self.client.post(
            "/api/projects/@current/tasks/bulk_reorder/",
            {"columns": {"in_progress": [str(task1.id), str(task2.id)]}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["updated"], 2)

        task1.refresh_from_db()
        task2.refresh_from_db()
        self.assertEqual(task1.current_stage.key, "in_progress")
        self.assertEqual(task2.current_stage.key, "in_progress")
        self.assertEqual(task1.position, 0)
        self.assertEqual(task2.position, 1)

    def test_progress(self):
        task = self.create_task()

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/progress/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["has_progress"], False)

    def test_progress_stream(self):
        task = self.create_task()

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/progress_stream/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["progress_updates"]), 0)
        self.assertIn("server_time", data)


class TestTaskProgressAPI(BaseTaskAPITest):
    def test_progress_with_no_progress_records(self):
        task = self.create_task()

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/progress/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertFalse(data["has_progress"])
        self.assertEqual(data["message"], "No execution progress found for this task")

    def test_progress_with_existing_records(self):
        task = self.create_task()

        progress = TaskProgress.objects.create(
            task=task,
            team=self.team,
            status=TaskProgress.Status.IN_PROGRESS,
            current_step="Processing data",
            completed_steps=2,
            total_steps=5,
            output_log="Step 1 completed\nStep 2 in progress",
            workflow_id="test-workflow-123",
        )

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/progress/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertTrue(data["has_progress"])
        self.assertEqual(data["id"], str(progress.id))
        self.assertEqual(data["status"], "in_progress")
        self.assertEqual(data["current_step"], "Processing data")
        self.assertEqual(data["completed_steps"], 2)
        self.assertEqual(data["total_steps"], 5)
        self.assertEqual(data["progress_percentage"], 40)
        self.assertEqual(data["output_log"], "Step 1 completed\nStep 2 in progress")
        self.assertEqual(data["workflow_id"], "test-workflow-123")

    def test_progress_stream_with_no_updates(self):
        task = self.create_task()

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/progress_stream/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["progress_updates"]), 0)
        self.assertIn("server_time", data)

    def test_progress_stream_with_updates(self):
        task = self.create_task()

        progress1 = TaskProgress.objects.create(
            task=task,
            team=self.team,
            status=TaskProgress.Status.STARTED,
            current_step="Initializing",
            completed_steps=0,
            total_steps=3,
        )

        progress2 = TaskProgress.objects.create(
            task=task,
            team=self.team,
            status=TaskProgress.Status.COMPLETED,
            current_step="Finished",
            completed_steps=3,
            total_steps=3,
        )

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/progress_stream/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["progress_updates"]), 2)

        # Most recent first
        recent_update = data["progress_updates"][0]
        self.assertEqual(recent_update["id"], str(progress2.id))
        self.assertEqual(recent_update["status"], "completed")
        self.assertEqual(recent_update["completed_steps"], 3)

        # Should include older progress
        self.assertEqual(len(data["progress_updates"]), 2)
        older_update = data["progress_updates"][1]
        self.assertEqual(older_update["id"], str(progress1.id))
        self.assertEqual(older_update["status"], "started")
        self.assertEqual(older_update["completed_steps"], 0)

    def test_progress_stream_with_since_parameter(self):
        task = self.create_task()

        old_progress = TaskProgress.objects.create(
            task=task, team=self.team, status=TaskProgress.Status.STARTED, current_step="Old step"
        )

        # Add some time gap
        import datetime

        from django.utils import timezone

        since_time = timezone.now()

        # Create newer progress after the 'since' time
        TaskProgress.objects.filter(id=old_progress.id).update(
            updated_at=timezone.now() + datetime.timedelta(seconds=1)
        )

        response = self.client.get(
            f"/api/projects/@current/tasks/{task.id}/progress_stream/", {"since": since_time.isoformat()}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        # Should include the updated progress
        self.assertEqual(len(data["progress_updates"]), 1)


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

    def test_workflows_feature_flag_required(self):
        self.set_tasks_feature_flag(False)
        workflow = self.create_workflow()

        endpoints = [
            ("/api/projects/@current/workflows/", "GET"),
            (f"/api/projects/@current/workflows/{workflow.id}/", "GET"),
            ("/api/projects/@current/workflows/", "POST"),
            (f"/api/projects/@current/workflows/{workflow.id}/", "PATCH"),
            (f"/api/projects/@current/workflows/{workflow.id}/", "DELETE"),
            (f"/api/projects/@current/workflows/{workflow.id}/set_default/", "POST"),
            (f"/api/projects/@current/workflows/{workflow.id}/deactivate/", "POST"),
            ("/api/projects/@current/workflows/create_default/", "POST"),
        ]

        for url, method in endpoints:
            response = getattr(self.client, method.lower())(url, format="json")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, f"Failed for {method} {url}")

    def test_tasks_feature_flag_required(self):
        self.set_tasks_feature_flag(False)
        task = self.create_task()

        endpoints = [
            ("/api/projects/@current/tasks/", "GET"),
            (f"/api/projects/@current/tasks/{task.id}/", "GET"),
            ("/api/projects/@current/tasks/", "POST"),
            (f"/api/projects/@current/tasks/{task.id}/", "PATCH"),
            (f"/api/projects/@current/tasks/{task.id}/", "DELETE"),
            (f"/api/projects/@current/tasks/{task.id}/update_stage/", "PATCH"),
            (f"/api/projects/@current/tasks/{task.id}/update_position/", "PATCH"),
            ("/api/projects/@current/tasks/bulk_reorder/", "POST"),
            (f"/api/projects/@current/tasks/{task.id}/progress/", "GET"),
            (f"/api/projects/@current/tasks/{task.id}/progress_stream/", "GET"),
        ]

        for url, method in endpoints:
            response = getattr(self.client, method.lower())(url, format="json")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, f"Failed for {method} {url}")

    def test_workflow_stages_feature_flag_required(self):
        self.set_tasks_feature_flag(False)
        workflow = self.create_workflow()
        stage = workflow.stages.first()

        endpoints = [
            (f"/api/projects/@current/workflows/{workflow.id}/stages/", "GET"),
            (f"/api/projects/@current/workflows/{workflow.id}/stages/{stage.id}/", "GET"),
            (f"/api/projects/@current/workflows/{workflow.id}/stages/", "POST"),
            (f"/api/projects/@current/workflows/{workflow.id}/stages/{stage.id}/", "PATCH"),
            (f"/api/projects/@current/workflows/{workflow.id}/stages/{stage.id}/", "DELETE"),
            (f"/api/projects/@current/workflows/{workflow.id}/stages/{stage.id}/archive/", "POST"),
        ]

        for url, method in endpoints:
            response = getattr(self.client, method.lower())(url, format="json")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, f"Failed for {method} {url}")

    def test_authentication_required(self):
        workflow = self.create_workflow()
        task = self.create_task(workflow=workflow)

        self.client.force_authenticate(None)

        endpoints = [
            ("/api/projects/@current/workflows/", "GET"),
            ("/api/projects/@current/tasks/", "GET"),
            (f"/api/projects/@current/workflows/{workflow.id}/stages/", "GET"),
            (f"/api/projects/@current/tasks/{task.id}/progress/", "GET"),
        ]

        for url, method in endpoints:
            response = getattr(self.client, method.lower())(url)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, f"Failed for {method} {url}")

    def test_cross_team_workflow_access_forbidden(self):
        # Create workflow in other team
        other_workflow = TaskWorkflow.objects.create(team=self.other_team, name="Other Team Workflow", is_default=True)

        # Try to access other team's workflow
        response = self.client.get(f"/api/projects/@current/workflows/{other_workflow.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Try to update other team's workflow
        response = self.client.patch(
            f"/api/projects/@current/workflows/{other_workflow.id}/", {"name": "Hacked Name"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Try to delete other team's workflow
        response = self.client.delete(f"/api/projects/@current/workflows/{other_workflow.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

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

    def test_cross_team_workflow_stage_access_forbidden(self):
        # Create workflow and stage in other team
        other_workflow = TaskWorkflow.objects.create(team=self.other_team, name="Other Team Workflow", is_default=True)
        other_stage = WorkflowStage.objects.create(workflow=other_workflow, name="Other Stage", key="other", position=0)

        # Try to access other team's stages - should return empty list, not 404
        # because the workflow exists but stages are filtered by team
        response = self.client.get(f"/api/projects/@current/workflows/{other_workflow.id}/stages/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 0)

        # Try to access specific other team's stage
        response = self.client.get(f"/api/projects/@current/workflows/{other_workflow.id}/stages/{other_stage.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Try to create stage in other team's workflow
        response = self.client.post(
            f"/api/projects/@current/workflows/{other_workflow.id}/stages/",
            {
                "workflow": str(other_workflow.id),
                "name": "Hacked Stage",
                "key": "hacked",
                "position": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_endpoints_only_return_team_resources(self):
        # Create resources in both teams
        my_workflow = self.create_workflow("My Workflow")
        my_task = self.create_task("My Task")

        other_workflow = TaskWorkflow.objects.create(team=self.other_team, name="Other Workflow", is_default=True)
        other_task = Task.objects.create(
            team=self.other_team,
            title="Other Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

        # List workflows should only return my team's workflows
        response = self.client.get("/api/projects/@current/workflows/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        workflow_ids = [w["id"] for w in response.json()["results"]]
        self.assertIn(str(my_workflow.id), workflow_ids)
        self.assertNotIn(str(other_workflow.id), workflow_ids)

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
            ("task:read", "GET", "/api/projects/@current/workflows/", True),
            ("task:read", "GET", f"/api/projects/@current/workflows/{{workflow_id}}/", True),
            ("no_scope", "GET", "/api/projects/@current/agents/", False),
            ("task:read", "POST", "/api/projects/@current/tasks/", False),
            ("task:read", "PATCH", f"/api/projects/@current/tasks/{{task_id}}/", False),
            ("task:read", "DELETE", f"/api/projects/@current/tasks/{{task_id}}/", False),
            ("task:read", "POST", "/api/projects/@current/workflows/", False),
            ("task:read", "PATCH", f"/api/projects/@current/workflows/{{workflow_id}}/", False),
            ("task:write", "GET", "/api/projects/@current/tasks/", True),
            ("task:write", "POST", "/api/projects/@current/tasks/", True),
            ("task:write", "PATCH", f"/api/projects/@current/tasks/{{task_id}}/", True),
            ("task:write", "DELETE", f"/api/projects/@current/tasks/{{task_id}}/", True),
            ("task:write", "POST", "/api/projects/@current/workflows/", True),
            ("task:write", "PATCH", f"/api/projects/@current/workflows/{{workflow_id}}/", True),
            ("other_scope:read", "GET", "/api/projects/@current/tasks/", False),
            ("other_scope:write", "POST", "/api/projects/@current/tasks/", False),
            ("*", "GET", "/api/projects/@current/tasks/", True),
            ("*", "POST", "/api/projects/@current/tasks/", True),
        ]
    )
    def test_scoped_api_key_permissions(self, scope, method, url_template, should_have_access):
        task = self.create_task()
        workflow = task.workflow

        api_key_value = generate_random_token_personal()

        PersonalAPIKey.objects.create(
            user=self.user,
            label=f"Test API Key - {scope}",
            secure_value=hash_key_value(api_key_value),
            scopes=[scope],
        )

        url = url_template.format(task_id=task.id, workflow_id=workflow.id)

        self.client.force_authenticate(None)

        data = {}
        if method == "POST" and "tasks" in url:
            data = {
                "title": "New Task",
                "description": "Description",
                "origin_product": Task.OriginProduct.USER_CREATED,
            }
        elif method == "POST" and "workflows" in url:
            data = {
                "name": "New Workflow",
                "description": "Description",
            }
        elif method == "PATCH" and "tasks" in url:
            data = {"title": "Updated Task"}
        elif method == "PATCH" and "workflows" in url:
            data = {"name": "Updated Workflow"}

        if method == "GET":
            response = self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {api_key_value}")
        elif method == "POST":
            response = self.client.post(url, data, format="json", HTTP_AUTHORIZATION=f"Bearer {api_key_value}")
        elif method == "PATCH":
            response = self.client.patch(url, data, format="json", HTTP_AUTHORIZATION=f"Bearer {api_key_value}")
        elif method == "DELETE":
            response = self.client.delete(url, HTTP_AUTHORIZATION=f"Bearer {api_key_value}")
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
