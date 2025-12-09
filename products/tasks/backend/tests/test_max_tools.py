import uuid

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from products.tasks.backend.max_tools import (
    CreateTaskTool,
    GetTaskRunLogsTool,
    GetTaskRunTool,
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

    def _create_task_sync(self, title="Test Task", description="Test Description", repository=None):
        return Task.objects.create(
            team=self.team,
            title=title,
            description=description,
            origin_product=Task.OriginProduct.USER_CREATED,
            repository=repository,
            created_by=self.user,
        )

    async def _create_task(self, title="Test Task", description="Test Description", repository=None):
        return await sync_to_async(self._create_task_sync)(title, description, repository)

    def _create_task_run_sync(self, task, status=TaskRun.Status.QUEUED, stage=None):
        return TaskRun.objects.create(task=task, team=self.team, status=status, stage=stage)

    async def _create_task_run(self, task, status=TaskRun.Status.QUEUED, stage=None):
        return await sync_to_async(self._create_task_run_sync)(task, status, stage)


class TestCreateTaskTool(BaseTaskToolTest):
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_task_success(self):
        tool = self._create_tool(CreateTaskTool)

        content, artifact = await tool._arun_impl(
            title="New Task", description="Task description", repository="posthog/posthog-js"
        )

        assert "Created task" in content
        assert "New Task" in content
        assert "task_id" in artifact
        assert artifact["title"] == "New Task"

        task = await sync_to_async(Task.objects.get)(id=artifact["task_id"])
        assert task.title == "New Task"
        assert task.description == "Task description"
        assert task.repository == "posthog/posthog-js"
        assert task.origin_product == Task.OriginProduct.USER_CREATED

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_task_without_repository(self):
        tool = self._create_tool(CreateTaskTool)

        content, artifact = await tool._arun_impl(title="Simple Task", description="No repo")

        assert "Created task" in content
        assert "task_id" in artifact

        task = await sync_to_async(Task.objects.get)(id=artifact["task_id"])
        assert task.repository is None


class TestRunTaskTool(BaseTaskToolTest):
    @patch("products.tasks.backend.max_tools.execute_task_processing_workflow")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_run_task_success(self, mock_execute_workflow):
        task = await self._create_task()
        tool = self._create_tool(RunTaskTool)

        content, artifact = await tool._arun_impl(task_id=str(task.id))

        assert "Started execution" in content
        assert artifact["task_id"] == str(task.id)
        assert "run_id" in artifact

        mock_execute_workflow.assert_called_once()
        call_kwargs = mock_execute_workflow.call_args[1]
        assert call_kwargs["task_id"] == str(task.id)
        assert call_kwargs["team_id"] == task.team.id

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_run_task_not_found(self):
        tool = self._create_tool(RunTaskTool)
        fake_id = str(uuid.uuid4())

        content, artifact = await tool._arun_impl(task_id=fake_id)

        assert "not found" in content
        assert artifact["error"] == "not_found"


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
        task2 = await self._create_task("Deleted Task")
        task2.deleted = True
        await sync_to_async(task2.save)()

        tool = self._create_tool(ListTasksTool)

        content, artifact = await tool._arun_impl()

        assert len(artifact["tasks"]) == 1
        assert artifact["tasks"][0]["title"] == "Active Task"


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
