import uuid

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized_class

from products.tasks.backend.max_tools import (
    CreateTaskTool,
    GetTaskRunLogsTool,
    GetTaskRunTool,
    ListRepositoriesTool,
    ListTaskRunsTool,
    ListTasksTool,
    RunTaskTool,
)
from products.tasks.backend.models import Task, TaskRun


class BaseTaskToolTest(BaseTest):
    def setUp(self):
        super().setUp()
        self._config: RunnableConfig = {
            "configurable": {
                "team": self.team,
                "user": self.user,
            },
        }

    def _create_tool(self, tool_class):
        return tool_class(team=self.team, user=self.user, config=self._config)

    def _create_task_sync(
        self,
        title="Test Task",
        description="Test Description",
        repository=None,
        origin_product=None,
        deleted=False,
    ):
        task = Task.objects.create(
            team=self.team,
            title=title,
            description=description,
            origin_product=origin_product or Task.OriginProduct.USER_CREATED,
            repository=repository,
            created_by=self.user,
        )
        if deleted:
            task.deleted = True
            task.save()
        return task

    async def _create_task(
        self,
        title="Test Task",
        description="Test Description",
        repository=None,
        origin_product=None,
        deleted=False,
    ):
        return await sync_to_async(self._create_task_sync)(title, description, repository, origin_product, deleted)

    def _create_task_run_sync(
        self,
        task,
        status=TaskRun.Status.QUEUED,
        stage=None,
        branch=None,
        error_message=None,
        output=None,
    ):
        return TaskRun.objects.create(
            task=task,
            team=self.team,
            status=status,
            stage=stage,
            branch=branch,
            error_message=error_message,
            output=output,
        )

    async def _create_task_run(
        self,
        task,
        status=TaskRun.Status.QUEUED,
        stage=None,
        branch=None,
        error_message=None,
        output=None,
    ):
        return await sync_to_async(self._create_task_run_sync)(task, status, stage, branch, error_message, output)


class TestCreateTaskTool(BaseTaskToolTest):
    @patch("products.tasks.backend.max_tools.execute_task_processing_workflow_async")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_task_success(self, mock_execute_workflow):
        tool = self._create_tool(CreateTaskTool)

        content, artifact = await tool._arun_impl(
            title="New Task", description="Task description", repository="posthog/posthog-js"
        )

        assert "Created and started task" in content
        assert "New Task" in content
        assert "task_id" in artifact
        assert "slug" in artifact
        assert "url" in artifact
        assert artifact["title"] == "New Task"

        task = await sync_to_async(Task.objects.get)(id=artifact["task_id"])
        assert task.title == "New Task"
        assert task.description == "Task description"
        assert task.repository == "posthog/posthog-js"
        mock_execute_workflow.assert_called_once()

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_task_sets_origin_product(self):
        tool = self._create_tool(CreateTaskTool)

        content, artifact = await tool._arun_impl(title="Origin Test", description="Test", repository="org/repo")

        task = await sync_to_async(Task.objects.get)(id=artifact["task_id"])
        assert task.origin_product == Task.OriginProduct.USER_CREATED

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_task_generates_slug(self):
        tool = self._create_tool(CreateTaskTool)

        content, artifact = await tool._arun_impl(title="Slug Test Task", description="Test", repository="org/repo")

        assert artifact["slug"] is not None
        assert len(artifact["slug"]) > 0

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_task_url_format(self):
        tool = self._create_tool(CreateTaskTool)

        content, artifact = await tool._arun_impl(title="URL Test", description="Test", repository="org/repo")

        assert "/project/" in artifact["url"]
        assert "/tasks/" in artifact["url"]
        assert artifact["task_id"] in artifact["url"]

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_task_without_github_integration(self):
        tool = self._create_tool(CreateTaskTool)

        content, artifact = await tool._arun_impl(title="No Integration", description="Test", repository="org/repo")

        assert "Created and started task" in content
        task = await sync_to_async(Task.objects.get)(id=artifact["task_id"])
        assert task.github_integration is None


class TestRunTaskTool(BaseTaskToolTest):
    @patch("products.tasks.backend.max_tools.execute_task_processing_workflow_async")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_run_task_success(self, mock_execute_workflow):
        task = await self._create_task(repository="org/repo")
        tool = self._create_tool(RunTaskTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "Started execution" in content
        assert artifact["task_id"] == str(task.id)
        assert "run_id" in artifact

        mock_execute_workflow.assert_called_once()

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_run_task_not_found(self):
        tool = self._create_tool(RunTaskTool)
        fake_id = str(uuid.uuid4())

        content, artifact = await tool._arun_impl(task_id=fake_id)

        assert "not found" in content
        assert artifact["error"] == "not_found"

    @patch("products.tasks.backend.max_tools.execute_task_processing_workflow_async")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_run_task_deleted_task(self, mock_execute_workflow):
        task = await self._create_task(deleted=True)
        tool = self._create_tool(RunTaskTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "not found" in content
        assert artifact["error"] == "not_found"
        mock_execute_workflow.assert_not_called()

    @patch("products.tasks.backend.max_tools.execute_task_processing_workflow_async")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_run_task_creates_queued_run(self, mock_execute_workflow):
        task = await self._create_task(repository="org/repo")
        tool = self._create_tool(RunTaskTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        run = await sync_to_async(TaskRun.objects.get)(id=artifact["run_id"])
        assert run.status == TaskRun.Status.QUEUED

    @patch("products.tasks.backend.max_tools.execute_task_processing_workflow_async")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_run_task_workflow_params(self, mock_execute_workflow):
        task = await self._create_task(repository="org/repo")
        tool = self._create_tool(RunTaskTool)

        await tool._arun_impl(task_id=str(task.id))

        call_kwargs = mock_execute_workflow.call_args[1]
        assert call_kwargs["task_id"] == str(task.id)
        assert call_kwargs["team_id"] == task.team.id
        assert call_kwargs["user_id"] == self.user.id
        assert "run_id" in call_kwargs

    @patch("products.tasks.backend.max_tools.execute_task_processing_workflow_async")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_run_task_other_team(self, mock_execute_workflow):
        from posthog.models import Organization, Team, User

        @sync_to_async
        def create_other_team_task():
            other_org = Organization.objects.create(name="Other Org")
            other_team = Team.objects.create(organization=other_org, name="Other Team")
            other_user = User.objects.create(email="other@test.com")
            return Task.objects.create(
                team=other_team,
                title="Other Team Task",
                description="Test",
                origin_product=Task.OriginProduct.USER_CREATED,
                created_by=other_user,
            )

        task = await create_other_team_task()
        tool = self._create_tool(RunTaskTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "not found" in content
        assert artifact["error"] == "not_found"
        mock_execute_workflow.assert_not_called()


class TestGetTaskRunTool(BaseTaskToolTest):
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_task_run_latest(self):
        task = await self._create_task()
        await self._create_task_run(task, status=TaskRun.Status.COMPLETED)
        run2 = await self._create_task_run(task, status=TaskRun.Status.IN_PROGRESS, stage="build")

        tool = self._create_tool(GetTaskRunTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "In Progress" in content
        assert artifact["run"]["run_id"] == str(run2.id)
        assert artifact["run"]["status"] == TaskRun.Status.IN_PROGRESS
        assert artifact["run"]["stage"] == "build"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_task_run_specific(self):
        task = await self._create_task()
        run1 = await self._create_task_run(task, status=TaskRun.Status.COMPLETED)
        await self._create_task_run(task, status=TaskRun.Status.IN_PROGRESS)

        tool = self._create_tool(GetTaskRunTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id), run_id=str(run1.id))

        assert artifact["run"]["run_id"] == str(run1.id)
        assert artifact["run"]["status"] == TaskRun.Status.COMPLETED

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_task_run_no_runs(self):
        task = await self._create_task()
        tool = self._create_tool(GetTaskRunTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "no runs yet" in content
        assert artifact["error"] == "no_runs"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_task_run_task_not_found(self):
        tool = self._create_tool(GetTaskRunTool)
        fake_id = str(uuid.uuid4())

        content, artifact = await tool._arun_impl(task_id=fake_id)

        assert "not found" in content
        assert artifact["error"] == "not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_task_run_run_not_found(self):
        task = await self._create_task()
        await self._create_task_run(task, status=TaskRun.Status.COMPLETED)
        tool = self._create_tool(GetTaskRunTool)
        fake_run_id = str(uuid.uuid4())

        content, artifact = await tool._arun_impl(task_id=str(task.id), run_id=fake_run_id)

        assert "not found" in content
        assert artifact["error"] == "run_not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_task_run_deleted_task(self):
        task = await self._create_task(deleted=True)
        tool = self._create_tool(GetTaskRunTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "not found" in content
        assert artifact["error"] == "not_found"


@parameterized_class(
    ("status", "expected_display"),
    [
        (TaskRun.Status.QUEUED, "Queued"),
        (TaskRun.Status.IN_PROGRESS, "In Progress"),
        (TaskRun.Status.COMPLETED, "Completed"),
        (TaskRun.Status.FAILED, "Failed"),
        (TaskRun.Status.CANCELLED, "Cancelled"),
    ],
)
class TestGetTaskRunToolStatusDisplay(BaseTaskToolTest):
    status: TaskRun.Status
    expected_display: str

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_status_display(self):
        task = await self._create_task()
        await self._create_task_run(task, status=self.status)

        tool = self._create_tool(GetTaskRunTool)
        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert self.expected_display in content
        assert artifact["run"]["status"] == self.status


@parameterized_class(
    ("field", "value", "expected_in_message"),
    [
        ("stage", "build", "Current stage: build"),
        ("branch", "fix/issue-123", "Branch: fix/issue-123"),
        ("error_message", "Something failed", "Error: Something failed"),
        ("output", "Task completed successfully", "Output: Task completed successfully"),
    ],
)
class TestGetTaskRunToolMessageFields(BaseTaskToolTest):
    field: str
    value: str
    expected_in_message: str

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_message_includes_field(self):
        task = await self._create_task()
        kwargs = {self.field: self.value}
        await self._create_task_run(task, status=TaskRun.Status.IN_PROGRESS, **kwargs)

        tool = self._create_tool(GetTaskRunTool)
        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert self.expected_in_message in content


class TestGetTaskRunLogsTool(BaseTaskToolTest):
    @patch("products.tasks.backend.max_tools.object_storage")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_logs_success(self, mock_storage):
        mock_storage.get_presigned_url.return_value = "https://s3.example.com/logs/test.jsonl?signed=true"

        task = await self._create_task()
        await self._create_task_run(task, status=TaskRun.Status.IN_PROGRESS)

        tool = self._create_tool(GetTaskRunLogsTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "Logs for task" in content
        assert "https://s3.example.com" in artifact["log_url"]
        assert artifact["expires_in"] == 3600

    @patch("products.tasks.backend.max_tools.object_storage")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_logs_presign_failed(self, mock_storage):
        mock_storage.get_presigned_url.return_value = None

        task = await self._create_task()
        await self._create_task_run(task, status=TaskRun.Status.IN_PROGRESS)

        tool = self._create_tool(GetTaskRunLogsTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "Unable to generate" in content
        assert artifact["error"] == "presign_failed"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_logs_task_not_found(self):
        tool = self._create_tool(GetTaskRunLogsTool)
        fake_id = str(uuid.uuid4())

        content, artifact = await tool._arun_impl(task_id=fake_id)

        assert "not found" in content
        assert artifact["error"] == "not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_logs_no_runs(self):
        task = await self._create_task()
        tool = self._create_tool(GetTaskRunLogsTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "no runs yet" in content
        assert artifact["error"] == "no_runs"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_logs_run_not_found(self):
        task = await self._create_task()
        await self._create_task_run(task, status=TaskRun.Status.IN_PROGRESS)
        tool = self._create_tool(GetTaskRunLogsTool)
        fake_run_id = str(uuid.uuid4())

        content, artifact = await tool._arun_impl(task_id=str(task.id), run_id=fake_run_id)

        assert "not found" in content
        assert artifact["error"] == "run_not_found"

    @patch("products.tasks.backend.max_tools.object_storage")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_logs_specific_run(self, mock_storage):
        mock_storage.get_presigned_url.return_value = "https://s3.example.com/logs/specific.jsonl"

        task = await self._create_task()
        run1 = await self._create_task_run(task, status=TaskRun.Status.COMPLETED)
        await self._create_task_run(task, status=TaskRun.Status.IN_PROGRESS)

        tool = self._create_tool(GetTaskRunLogsTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id), run_id=str(run1.id))

        assert artifact["run_id"] == str(run1.id)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_logs_deleted_task(self):
        task = await self._create_task(deleted=True)
        tool = self._create_tool(GetTaskRunLogsTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "not found" in content
        assert artifact["error"] == "not_found"


class TestListTasksTool(BaseTaskToolTest):
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_tasks_empty(self):
        tool = self._create_tool(ListTasksTool)

        content, artifact = await tool._arun_impl()

        assert "No tasks found" in content
        assert artifact["tasks"] == []

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_tasks_with_results(self):
        await self._create_task("Task 1")
        await self._create_task("Task 2")

        tool = self._create_tool(ListTasksTool)

        content, artifact = await tool._arun_impl()

        assert "Found 2 task(s)" in content
        assert len(artifact["tasks"]) == 2

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_repository(self):
        await self._create_task("Task 1", repository="posthog/posthog-js")
        await self._create_task("Task 2", repository="posthog/posthog")

        tool = self._create_tool(ListTasksTool)

        content, artifact = await tool._arun_impl(repository="posthog/posthog-js")

        assert len(artifact["tasks"]) == 1
        assert artifact["tasks"][0]["repository"] == "posthog/posthog-js"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_tasks_respects_limit(self):
        for i in range(5):
            await self._create_task(f"Task {i}")

        tool = self._create_tool(ListTasksTool)

        content, artifact = await tool._arun_impl(limit=3)

        assert len(artifact["tasks"]) == 3

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_tasks_excludes_deleted(self):
        await self._create_task("Active Task")
        await self._create_task("Deleted Task", deleted=True)

        tool = self._create_tool(ListTasksTool)

        content, artifact = await tool._arun_impl()

        assert len(artifact["tasks"]) == 1
        assert artifact["tasks"][0]["title"] == "Active Task"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_origin_product(self):
        await self._create_task("User Task", origin_product=Task.OriginProduct.USER_CREATED)
        await self._create_task("Error Task", origin_product=Task.OriginProduct.ERROR_TRACKING)

        tool = self._create_tool(ListTasksTool)

        content, artifact = await tool._arun_impl(origin_product=Task.OriginProduct.ERROR_TRACKING)

        assert len(artifact["tasks"]) == 1
        assert artifact["tasks"][0]["title"] == "Error Task"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_tasks_repo_partial_match(self):
        await self._create_task("JS Task", repository="posthog/posthog-js")
        await self._create_task("Main Task", repository="posthog/posthog")

        tool = self._create_tool(ListTasksTool)

        content, artifact = await tool._arun_impl(repository="posthog-js")

        assert len(artifact["tasks"]) == 1
        assert artifact["tasks"][0]["repository"] == "posthog/posthog-js"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_tasks_repo_case_insensitive(self):
        await self._create_task("Task", repository="PostHog/PostHog-JS")

        tool = self._create_tool(ListTasksTool)

        content, artifact = await tool._arun_impl(repository="posthog/posthog-js")

        assert len(artifact["tasks"]) == 1

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_tasks_ordered_by_created_at(self):
        task1 = await self._create_task("First Task")
        task2 = await self._create_task("Second Task")

        tool = self._create_tool(ListTasksTool)

        content, artifact = await tool._arun_impl()

        assert artifact["tasks"][0]["id"] == str(task2.id)
        assert artifact["tasks"][1]["id"] == str(task1.id)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_tasks_team_isolation(self):
        from posthog.models import Organization, Team, User

        @sync_to_async
        def create_other_team_task():
            other_org = Organization.objects.create(name="Other Org")
            other_team = Team.objects.create(organization=other_org, name="Other Team")
            other_user = User.objects.create(email="other@test.com")
            Task.objects.create(
                team=other_team,
                title="Other Team Task",
                description="Test",
                origin_product=Task.OriginProduct.USER_CREATED,
                created_by=other_user,
            )

        await create_other_team_task()
        await self._create_task("My Task")

        tool = self._create_tool(ListTasksTool)

        content, artifact = await tool._arun_impl()

        assert len(artifact["tasks"]) == 1
        assert artifact["tasks"][0]["title"] == "My Task"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_tasks_includes_run_status(self):
        task = await self._create_task("Task with run")
        await self._create_task_run(task, status=TaskRun.Status.COMPLETED)

        tool = self._create_tool(ListTasksTool)

        content, artifact = await tool._arun_impl()

        assert "Completed" in content
        assert artifact["tasks"][0]["status"] == TaskRun.Status.COMPLETED

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_tasks_output_includes_ids(self):
        task = await self._create_task("Task with ID")

        tool = self._create_tool(ListTasksTool)

        content, artifact = await tool._arun_impl()

        assert f"ID: {task.id}" in content


@parameterized_class(
    ("filter_value", "should_match"),
    [
        ("posthog/posthog-js", True),
        ("PostHog/PostHog-JS", True),
        ("posthog-js", True),
        ("posthog/posthog", False),
    ],
)
class TestListTasksToolRepositoryFiltering(BaseTaskToolTest):
    filter_value: str
    should_match: bool

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_repository_filtering(self):
        await self._create_task("Target Task", repository="posthog/posthog-js")

        tool = self._create_tool(ListTasksTool)
        content, artifact = await tool._arun_impl(repository=self.filter_value)

        if self.should_match:
            assert len(artifact["tasks"]) == 1
        else:
            assert len(artifact["tasks"]) == 0


class TestListTaskRunsTool(BaseTaskToolTest):
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_runs_success(self):
        task = await self._create_task()
        run1 = await self._create_task_run(task, status=TaskRun.Status.COMPLETED)
        run2 = await self._create_task_run(task, status=TaskRun.Status.IN_PROGRESS, stage="plan")

        tool = self._create_tool(ListTaskRunsTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "2 run(s)" in content
        assert len(artifact["runs"]) == 2
        assert artifact["runs"][0]["run_id"] == str(run2.id)
        assert artifact["runs"][1]["run_id"] == str(run1.id)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_runs_no_runs(self):
        task = await self._create_task()
        tool = self._create_tool(ListTaskRunsTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "no runs yet" in content
        assert artifact["runs"] == []

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_runs_task_not_found(self):
        tool = self._create_tool(ListTaskRunsTool)
        fake_id = str(uuid.uuid4())

        content, artifact = await tool._arun_impl(task_id=fake_id)

        assert "not found" in content
        assert artifact["error"] == "not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_runs_respects_limit(self):
        task = await self._create_task()
        for _ in range(5):
            await self._create_task_run(task, status=TaskRun.Status.COMPLETED)

        tool = self._create_tool(ListTaskRunsTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id), limit=3)

        assert len(artifact["runs"]) == 3

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_runs_ordered_by_created_at(self):
        task = await self._create_task()
        run1 = await self._create_task_run(task, status=TaskRun.Status.COMPLETED)
        run2 = await self._create_task_run(task, status=TaskRun.Status.IN_PROGRESS)

        tool = self._create_tool(ListTaskRunsTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert artifact["runs"][0]["run_id"] == str(run2.id)
        assert artifact["runs"][1]["run_id"] == str(run1.id)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_runs_deleted_task(self):
        task = await self._create_task(deleted=True)
        tool = self._create_tool(ListTaskRunsTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "not found" in content
        assert artifact["error"] == "not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_runs_output_includes_ids(self):
        task = await self._create_task()
        run = await self._create_task_run(task, status=TaskRun.Status.COMPLETED)

        tool = self._create_tool(ListTaskRunsTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert f"Run ID: {run.id}" in content

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_runs_shows_error_truncated(self):
        task = await self._create_task()
        long_error = "E" * 150
        await self._create_task_run(task, status=TaskRun.Status.FAILED, error_message=long_error)

        tool = self._create_tool(ListTaskRunsTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "Error:" in content
        assert "..." in content
        assert len(content.split("Error:")[1].split("\n")[0]) < 120

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_runs_short_error_no_ellipsis(self):
        task = await self._create_task()
        short_error = "Short error message"
        await self._create_task_run(task, status=TaskRun.Status.FAILED, error_message=short_error)

        tool = self._create_tool(ListTaskRunsTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "Error: Short error message" in content
        assert "..." not in content


class TestListRepositoriesTool(BaseTaskToolTest):
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_repositories_no_integration(self):
        tool = self._create_tool(ListRepositoriesTool)

        content, artifact = await tool._arun_impl()

        assert "No GitHub repositories available" in content
        assert "/settings/project-integrations" in content
        assert artifact["repositories"] == []
        assert artifact["settings_url"] == "/settings/project-integrations"

    @patch("posthog.models.integration.GitHubIntegration")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_repositories_success(self, mock_github_class):
        from posthog.models.integration import Integration

        @sync_to_async
        def create_integration():
            return Integration.objects.create(
                team=self.team,
                kind="github",
                integration_id="12345",
                config={"account": {"name": "posthog"}},
            )

        await create_integration()

        mock_github_instance = mock_github_class.return_value
        mock_github_instance.organization.return_value = "posthog"
        mock_github_instance.list_repositories.return_value = ["posthog-js", "posthog-python", "posthog"]

        tool = self._create_tool(ListRepositoriesTool)

        content, artifact = await tool._arun_impl()

        assert "3 repository(ies)" in content
        assert len(artifact["repositories"]) == 3
        assert artifact["repositories"][0]["repository"] == "posthog/posthog-js"
        assert artifact["repositories"][0]["organization"] == "posthog"
        assert artifact["repositories"][0]["name"] == "posthog-js"

    @patch("posthog.models.integration.GitHubIntegration")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_repositories_with_search(self, mock_github_class):
        from posthog.models.integration import Integration

        @sync_to_async
        def create_integration():
            return Integration.objects.create(
                team=self.team,
                kind="github",
                integration_id="12345",
                config={"account": {"name": "posthog"}},
            )

        await create_integration()

        mock_github_instance = mock_github_class.return_value
        mock_github_instance.organization.return_value = "posthog"
        mock_github_instance.list_repositories.return_value = ["posthog-js", "posthog-python", "posthog"]

        tool = self._create_tool(ListRepositoriesTool)

        content, artifact = await tool._arun_impl(search="python")

        assert "1 repository(ies)" in content
        assert len(artifact["repositories"]) == 1
        assert artifact["repositories"][0]["repository"] == "posthog/posthog-python"

    @patch("posthog.models.integration.GitHubIntegration")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_repositories_search_case_insensitive(self, mock_github_class):
        from posthog.models.integration import Integration

        @sync_to_async
        def create_integration():
            return Integration.objects.create(
                team=self.team,
                kind="github",
                integration_id="12345",
                config={"account": {"name": "PostHog"}},
            )

        await create_integration()

        mock_github_instance = mock_github_class.return_value
        mock_github_instance.organization.return_value = "PostHog"
        mock_github_instance.list_repositories.return_value = ["PostHog-JS"]

        tool = self._create_tool(ListRepositoriesTool)

        content, artifact = await tool._arun_impl(search="posthog-js")

        assert len(artifact["repositories"]) == 1

    @patch("posthog.models.integration.GitHubIntegration")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_repositories_search_no_match(self, mock_github_class):
        from posthog.models.integration import Integration

        @sync_to_async
        def create_integration():
            return Integration.objects.create(
                team=self.team,
                kind="github",
                integration_id="12345",
                config={"account": {"name": "posthog"}},
            )

        await create_integration()

        mock_github_instance = mock_github_class.return_value
        mock_github_instance.organization.return_value = "posthog"
        mock_github_instance.list_repositories.return_value = ["posthog-js", "posthog-python"]

        tool = self._create_tool(ListRepositoriesTool)

        content, artifact = await tool._arun_impl(search="nonexistent")

        assert "No repositories found matching 'nonexistent'" in content
        assert artifact["repositories"] == []

    @patch("posthog.models.integration.GitHubIntegration")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_repositories_handles_integration_error(self, mock_github_class):
        from posthog.models.integration import Integration

        @sync_to_async
        def create_integration():
            return Integration.objects.create(
                team=self.team,
                kind="github",
                integration_id="12345",
                config={"account": {"name": "posthog"}},
            )

        await create_integration()

        mock_github_class.side_effect = Exception("API error")

        tool = self._create_tool(ListRepositoriesTool)

        content, artifact = await tool._arun_impl()

        assert "No GitHub repositories available" in content
        assert "/settings/project-integrations" in content
        assert artifact["repositories"] == []
        assert artifact["settings_url"] == "/settings/project-integrations"

    @patch("posthog.models.integration.GitHubIntegration")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_list_repositories_team_isolation(self, mock_github_class):
        from posthog.models import Organization, Team
        from posthog.models.integration import Integration

        @sync_to_async
        def create_other_team_integration():
            other_org = Organization.objects.create(name="Other Org")
            other_team = Team.objects.create(organization=other_org, name="Other Team")
            Integration.objects.create(
                team=other_team,
                kind="github",
                integration_id="other-12345",
                config={"account": {"name": "other-org"}},
            )

        await create_other_team_integration()

        tool = self._create_tool(ListRepositoriesTool)

        content, artifact = await tool._arun_impl()

        assert "No GitHub repositories available" in content
        assert "/settings/project-integrations" in content
        assert artifact["repositories"] == []
        assert artifact["settings_url"] == "/settings/project-integrations"
