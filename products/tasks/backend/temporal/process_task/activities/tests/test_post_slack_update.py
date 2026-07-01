import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.temporal.process_task.activities.post_slack_update import (
    SLACK_DENIAL_STOP_MESSAGE,
    SLACK_PERMISSION_REJECTION_ERROR_FRAGMENT,
    SLACK_RECOVERY_STRATEGY_CONNECT_THEN_REPLAN,
    SLACK_RECOVERY_STRATEGY_RETRY,
    SLACK_RECOVERY_STRATEGY_UNBLOCK_AND_REPLAN,
    _classify_failure_recovery,
    _failure_recovery_prompt,
    _post_error_once,
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
