import pytest

from django.core.exceptions import ValidationError

from asgiref.sync import sync_to_async

from products.tasks.backend.models import Task
from products.tasks.backend.temporal.exceptions import TaskInvalidStateError, TaskNotFoundError
from products.tasks.backend.temporal.process_task.activities.get_task_details import TaskDetails, get_task_details


class TestGetTaskDetailsActivity:
    async def _create_task_with_repo(self, ateam, auser, task_workflow, github_integration, repo_config):
        workflow, stages = task_workflow
        backlog_stage = stages[0]

        return await sync_to_async(Task.objects.create)(
            team=ateam,
            title="Test Task",
            description="Test task description",
            origin_product=Task.OriginProduct.USER_CREATED,
            workflow=workflow,
            current_stage=backlog_stage,
            position=0,
            github_integration=github_integration,
            repository_config=repo_config,
            created_by=auser,
        )

    async def _cleanup_task(self, task):
        await sync_to_async(task.delete)()

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_get_task_details_success(self, activity_environment, test_task):
        result = await activity_environment.run(get_task_details, str(test_task.id))

        assert isinstance(result, TaskDetails)
        assert result.task_id == str(test_task.id)
        assert result.team_id == test_task.team_id
        assert result.github_integration_id == test_task.github_integration_id
        assert result.repository == "posthog/posthog-js"

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_get_task_details_task_not_found(self, activity_environment):
        non_existent_task_id = "550e8400-e29b-41d4-a716-446655440000"

        with pytest.raises(TaskNotFoundError):
            await activity_environment.run(get_task_details, non_existent_task_id)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_get_task_details_invalid_uuid(self, activity_environment):
        invalid_task_id = "not-a-uuid"

        with pytest.raises(ValidationError):
            await activity_environment.run(get_task_details, invalid_task_id)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_get_task_details_with_different_repository(
        self, activity_environment, ateam, auser, task_workflow, github_integration
    ):
        task = await self._create_task_with_repo(
            ateam, auser, task_workflow, github_integration, {"organization": "posthog", "repository": "posthog-js"}
        )

        try:
            result = await activity_environment.run(get_task_details, str(task.id))

            assert result.task_id == str(task.id)
            assert result.team_id == task.team_id
            assert result.github_integration_id == github_integration.id
            assert result.repository == "posthog/posthog-js"
        finally:
            await self._cleanup_task(task)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_get_task_details_with_missing_repository(
        self, activity_environment, ateam, auser, task_workflow, github_integration
    ):
        task = await self._create_task_with_repo(
            ateam,
            auser,
            task_workflow,
            github_integration,
            {"organization": "test-org"},  # Missing "repository" key
        )

        try:
            with pytest.raises(TaskInvalidStateError):
                await activity_environment.run(get_task_details, str(task.id))
        finally:
            await self._cleanup_task(task)
