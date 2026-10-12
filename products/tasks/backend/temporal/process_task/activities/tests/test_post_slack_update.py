import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from products.slack_app.backend.services.slack_welcome_messages import github_connect_url
from products.tasks.backend.temporal.process_task.activities.post_slack_update import (
    SLACK_DENIAL_STOP_MESSAGE,
    SLACK_PERMISSION_REJECTION_ERROR_FRAGMENT,
    SLACK_RECOVERY_STRATEGY_CONNECT_THEN_REPLAN,
    SLACK_RECOVERY_STRATEGY_RECONNECT_GITHUB,
    SLACK_RECOVERY_STRATEGY_RETRY,
    SLACK_RECOVERY_STRATEGY_UNBLOCK_AND_REPLAN,
    _classify_failure_recovery,
    _failure_recovery_prompt,
    _post_cancelled_once,
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
        (
            "GitHub user integration for this run requires reauthorization",
            SLACK_RECOVERY_STRATEGY_RECONNECT_GITHUB,
            "Connect your GitHub in PostHog settings",
        ),
        (
            "GitHub user integration requires reauthorization and no team installation is available",
            SLACK_RECOVERY_STRATEGY_RECONNECT_GITHUB,
            "Connect your GitHub in PostHog settings",
        ),
    ],
)
def test_classify_failure_recovery(error: str, expected_strategy: str, expected_prompt_fragment: str) -> None:
    assert _classify_failure_recovery(error) == expected_strategy
    assert expected_prompt_fragment in _failure_recovery_prompt(error)


@override_settings(SITE_URL="http://localhost:8000")
def test_reconnect_github_prompt_links_the_settings_flow() -> None:
    prompt = _failure_recovery_prompt("GitHub user integration for this run requires reauthorization", 42)

    assert f"<{github_connect_url(42)}|Connect your GitHub in PostHog settings>" in prompt


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


@patch("products.tasks.backend.models.TaskRun.update_state_atomic")
def test_cancelled_run_clears_progress_without_posting(mock_update_state: MagicMock) -> None:
    task_run = MagicMock()
    task_run.state = {}
    handler = MagicMock(spec=["update_reaction", "delete_progress"])

    _post_cancelled_once(task_run, handler)

    handler.update_reaction.assert_called_once_with("hedgehog")
    handler.delete_progress.assert_called_once_with()
    mock_update_state.assert_called_once()
