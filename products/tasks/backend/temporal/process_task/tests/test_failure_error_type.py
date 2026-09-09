from unittest import TestCase

import temporalio.exceptions
from parameterized import parameterized

from products.tasks.backend.temporal.process_task.workflow import _failure_error_type


class TestFailureErrorType(TestCase):
    @parameterized.expand(
        [
            (
                "application_error_type",
                temporalio.exceptions.ApplicationError("boom", type="SandboxProvisionError"),
                "SandboxProvisionError",
            ),
            (
                "timeout_start_to_close",
                temporalio.exceptions.TimeoutError(
                    "timed out",
                    type=temporalio.exceptions.TimeoutType.START_TO_CLOSE,
                    last_heartbeat_details=[],
                ),
                "start_to_close",
            ),
            (
                "timeout_heartbeat",
                temporalio.exceptions.TimeoutError(
                    "timed out",
                    type=temporalio.exceptions.TimeoutType.HEARTBEAT,
                    last_heartbeat_details=[],
                ),
                "heartbeat",
            ),
            (
                "timeout_without_type",
                temporalio.exceptions.TimeoutError("timed out", type=None, last_heartbeat_details=[]),
                "RuntimeError",
            ),
            ("no_cause", None, "RuntimeError"),
            (
                "cause_without_type",
                temporalio.exceptions.CancelledError("cancelled"),
                "RuntimeError",
            ),
            (
                "application_error_empty_type",
                temporalio.exceptions.ApplicationError("boom", type=""),
                "RuntimeError",
            ),
        ]
    )
    def test_always_returns_a_string(self, _name: str, cause: BaseException | None, expected: str) -> None:
        result = _failure_error_type(cause, RuntimeError("outer"))
        assert result == expected
        assert isinstance(result, str)
