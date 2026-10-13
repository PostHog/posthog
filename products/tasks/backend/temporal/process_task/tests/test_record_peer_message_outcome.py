import pytest

from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    RetryState,
    TimeoutError as TemporalTimeoutError,
)

from products.tasks.backend.temporal.process_task.activities.record_peer_message_outcome import (
    is_timeout_activity_failure,
)


def _activity_error(cause: BaseException) -> ActivityError:
    error = ActivityError(
        "activity failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type="send_followup_to_sandbox",
        activity_id="1",
        retry_state=RetryState.TIMEOUT,
    )
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    "error,expected",
    [
        # The wire shape a heartbeat/start-to-close timeout reaches the workflow as:
        # ActivityError wrapping temporalio's TimeoutError. Misclassifying it as
        # terminal drops the orphaned attempt's later delivered write.
        (_activity_error(TemporalTimeoutError("heartbeat timeout", type=None, last_heartbeat_details=[])), True),
        (TemporalTimeoutError("start to close", type=None, last_heartbeat_details=[]), True),
        (_activity_error(ApplicationError("sandbox exploded", non_retryable=True)), False),
        (RuntimeError("worker died"), False),
    ],
)
def test_is_timeout_activity_failure(error, expected):
    assert is_timeout_activity_failure(error) is expected
