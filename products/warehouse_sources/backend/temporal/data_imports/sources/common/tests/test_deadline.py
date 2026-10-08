import threading
import contextvars

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.deadline import (
    DeadlineExceededError,
    run_with_deadline,
)

_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="unset")


def test_returns_the_result_with_the_callers_context() -> None:
    _REQUEST_ID.set("from-caller")

    assert run_with_deadline(_REQUEST_ID.get, timeout_seconds=5, thread_name="t") == "from-caller"


def test_raises_the_error_of_the_operation() -> None:
    def _fail() -> None:
        raise TimeoutError("driver timeout")

    with pytest.raises(TimeoutError, match="driver timeout"):
        run_with_deadline(_fail, timeout_seconds=5, thread_name="t")


def test_an_operation_that_hangs_raises_at_the_deadline_and_does_not_hold_the_caller() -> None:
    release = threading.Event()
    try:
        with pytest.raises(DeadlineExceededError) as error:
            run_with_deadline(release.wait, timeout_seconds=0.05, thread_name="hung-driver-call")
    finally:
        release.set()

    assert error.value.timeout_seconds == 0.05
    abandoned = [thread for thread in threading.enumerate() if thread.name == "hung-driver-call"]
    assert all(thread.daemon for thread in abandoned)
