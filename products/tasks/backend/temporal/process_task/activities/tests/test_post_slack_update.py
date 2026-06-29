import pytest

from products.tasks.backend.temporal.process_task.activities.post_slack_update import (
    SLACK_RECOVERY_STRATEGY_CONNECT_THEN_REPLAN,
    SLACK_RECOVERY_STRATEGY_RETRY,
    SLACK_RECOVERY_STRATEGY_UNBLOCK_AND_REPLAN,
    _classify_failure_recovery,
    _failure_recovery_prompt,
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
