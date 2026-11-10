"""The attempt number of a data import across every execution of its activity.

A workflow that runs the import activity again after a worker hand-off starts a new activity
execution, and Temporal numbers the attempts of that execution from 1 again. The import needs a
number that stays unique in the workflow run: it names the folder and the queue rows of each
attempt, and decides whether the attempt may reset the destination table.
"""

from contextvars import ContextVar
from typing import Literal

from posthog.temporal.common.activity_context import current_activity_attempt

_ATTEMPTS_BEFORE_THIS_EXECUTION: ContextVar[int] = ContextVar("data_import_attempts_before_this_execution", default=0)

ImportAttemptCause = Literal["first", "handoff", "retry"]


def set_attempts_before_this_execution(attempts: int) -> None:
    _ATTEMPTS_BEFORE_THIS_EXECUTION.set(max(attempts, 0))


def current_import_attempt() -> int:
    return _ATTEMPTS_BEFORE_THIS_EXECUTION.get() + current_activity_attempt()


def current_import_attempt_cause() -> ImportAttemptCause:
    """Why this attempt runs.

    `retry` means Temporal started the attempt: the attempt before it failed, timed out, or left
    a worker that does not return a hand-off result.
    """
    if current_activity_attempt() > 1:
        return "retry"
    return "handoff" if _ATTEMPTS_BEFORE_THIS_EXECUTION.get() > 0 else "first"
