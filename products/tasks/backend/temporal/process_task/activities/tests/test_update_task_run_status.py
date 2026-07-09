import pytest
from unittest.mock import patch

from asgiref.sync import async_to_sync

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.activities.update_task_run_status import (
    UpdateTaskRunStatusInput,
    update_task_run_status,
)

TOKEN_USAGE = {"input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500, "turns": 3}


@pytest.mark.requires_secrets
class TestUpdateTaskRunStatusActivity:
    @pytest.mark.django_db(transaction=True)
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

    @pytest.mark.django_db(transaction=True)
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

    @pytest.mark.django_db(transaction=True)
    @patch("products.tasks.backend.models.TaskRun.publish_stream_state_event")
    def test_publishes_stream_state_event(self, mock_publish_stream_state_event, activity_environment, test_task_run):
        input_data = UpdateTaskRunStatusInput(run_id=str(test_task_run.id), status=TaskRun.Status.IN_PROGRESS)

        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        mock_publish_stream_state_event.assert_called_once()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "status,expected_event",
        [
            (TaskRun.Status.COMPLETED, "task_run_completed"),
            (TaskRun.Status.FAILED, "task_run_failed"),
        ],
    )
    @patch("products.tasks.backend.temporal.process_task.activities.update_task_run_status.record_run_token_usage")
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_terminal_transition_captures_analytics_with_usage(
        self, mock_capture, mock_record, activity_environment, test_task_run, status, expected_event
    ):
        test_task_run.state = {
            **(test_task_run.state or {}),
            "token_usage": dict(TOKEN_USAGE),
            "rtk_effective": True,
        }
        test_task_run.save(update_fields=["state"])

        input_data = UpdateTaskRunStatusInput(
            run_id=str(test_task_run.id),
            status=status,
            error_message="boom" if status == TaskRun.Status.FAILED else None,
        )
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        captured = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == expected_event]
        assert len(captured) == 1
        props = captured[0].kwargs["properties"]
        assert props["input_tokens"] == 1200
        assert props["total_tokens"] == 1500
        assert props["usage_turns"] == 3
        assert props["rtk_enabled"] is True
        assert props["run_environment"] == test_task_run.environment
        mock_record.assert_called_once()
        assert mock_record.call_args.kwargs["rtk_enabled"] is True
        assert mock_record.call_args.kwargs["status"] == status

    @pytest.mark.django_db(transaction=True)
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_repeated_terminal_update_does_not_double_capture(self, mock_capture, activity_environment, test_task_run):
        input_data = UpdateTaskRunStatusInput(run_id=str(test_task_run.id), status=TaskRun.Status.COMPLETED)
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)

        completed = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == "task_run_completed"]
        assert len(completed) == 1

    @pytest.mark.django_db(transaction=True)
    def test_handles_non_existent_task_run(self, activity_environment):
        non_existent_run_id = "550e8400-e29b-41d4-a716-446655440000"
        input_data = UpdateTaskRunStatusInput(
            run_id=non_existent_run_id,
            status=TaskRun.Status.IN_PROGRESS,
        )
        async_to_sync(activity_environment.run)(update_task_run_status, input_data)
