import pytest
from unittest.mock import MagicMock, patch

from django.db import OperationalError

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.activities.post_slack_update import (
    SLACK_DENIAL_STOP_MESSAGE,
    SLACK_PERMISSION_REJECTION_ERROR_FRAGMENT,
    SLACK_RECOVERY_STRATEGY_CONNECT_THEN_REPLAN,
    SLACK_RECOVERY_STRATEGY_RETRY,
    SLACK_RECOVERY_STRATEGY_UNBLOCK_AND_REPLAN,
    PostSlackUpdateInput,
    _classify_failure_recovery,
    _failure_recovery_prompt,
    _post_error_once,
    post_slack_update,
)


@pytest.mark.parametrize(
    "error, expected_strategy, expected_prompt_fragment",
    [
        (
            "No connected GitHub integration was found for this user",
            SLACK_RECOVERY_STRATEGY_CONNECT_THEN_REPLAN,
            "re-plan against the current connections",
        ),
        (
            "User-authored run run-1 requires a linked GitHub account with repo access.",
            SLACK_RECOVERY_STRATEGY_CONNECT_THEN_REPLAN,
            "connecting the missing tool",
        ),
        (
            "Slack run requires an acting user before refreshing GitHub credentials.",
            SLACK_RECOVERY_STRATEGY_CONNECT_THEN_REPLAN,
            "connecting the missing tool",
        ),
        (
            "Task is infeasible without the missing information",
            SLACK_RECOVERY_STRATEGY_UNBLOCK_AND_REPLAN,
            "missing detail",
        ),
        (
            "Internal error: API Error: 529 overloaded_error",
            SLACK_RECOVERY_STRATEGY_RETRY,
            "retry",
        ),
    ],
)
def test_classify_failure_recovery(error: str, expected_strategy: str, expected_prompt_fragment: str) -> None:
    assert _classify_failure_recovery(error) == expected_strategy
    assert expected_prompt_fragment in _failure_recovery_prompt(error)


@patch("products.tasks.backend.models.TaskRun.update_state_atomic")
def test_suppressed_permission_rejection_posts_note_instead_of_error(mock_update_state: MagicMock) -> None:
    task_run = MagicMock()
    task_run.state = {"slack_permission_rejected": True}
    handler = MagicMock()

    _post_error_once(
        task_run,
        handler,
        f"agent stopped: {SLACK_PERMISSION_REJECTION_ERROR_FRAGMENT}",
        task_url=None,
    )

    handler.post_note.assert_called_once_with(SLACK_DENIAL_STOP_MESSAGE)
    handler.post_error.assert_not_called()
    mock_update_state.assert_called_once()


def test_retries_transient_db_connection_drop(activity_environment) -> None:
    # A pooled pgbouncer connection dropped mid-request raises OperationalError on the
    # activity's early TaskRun read. The retry-once guard must evict the dead connection and
    # re-query rather than letting the transient blip escape as error-tracking noise; here the
    # retry lands on the DoesNotExist path, so the activity resolves without raising.
    with patch("products.tasks.backend.models.TaskRun") as mock_task_run:
        mock_task_run.DoesNotExist = TaskRun.DoesNotExist
        mock_task_run.objects.select_related.return_value.get.side_effect = [
            OperationalError("[Errno -2] Name or service not known"),
            TaskRun.DoesNotExist(),
        ]

        activity_environment.run(
            post_slack_update,
            PostSlackUpdateInput(run_id="run-1", slack_thread_context={}),
        )

    assert mock_task_run.objects.select_related.return_value.get.call_count == 2
