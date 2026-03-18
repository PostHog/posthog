import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.activities.update_task_run_status import (
    UpdateTaskRunStatusInput,
    update_task_run_status,
)


@pytest.mark.requires_secrets
class TestUpdateTaskRunStatusActivity:
    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "status,sets_completed_at",
        [
            (TaskRun.Status.IN_PROGRESS, False),
            (TaskRun.Status.COMPLETED, True),
            (TaskRun.Status.FAILED, True),
            (TaskRun.Status.CANCELLED, False),
        ],
    )
    def test_updates_status(self, activity_environment, test_task_run, status, sets_completed_at):
        input_data = UpdateTaskRunStatusInput(run_id=str(test_task_run.id), status=status)
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        test_task_run.refresh_from_db()
        assert test_task_run.status == status
        if sets_completed_at:
            assert test_task_run.completed_at is not None
        else:
            assert test_task_run.completed_at is None

    @pytest.mark.django_db
    def test_updates_error_message(self, activity_environment, test_task_run):
        error_msg = "Something went wrong"
        input_data = UpdateTaskRunStatusInput(
            run_id=str(test_task_run.id),
            status=TaskRun.Status.FAILED,
            error_message=error_msg,
        )
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        test_task_run.refresh_from_db()
        assert test_task_run.error_message == error_msg

    @pytest.mark.django_db
    def test_handles_non_existent_task_run(self, activity_environment):
        non_existent_run_id = "550e8400-e29b-41d4-a716-446655440000"
        input_data = UpdateTaskRunStatusInput(
            run_id=non_existent_run_id,
            status=TaskRun.Status.IN_PROGRESS,
        )
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)
