from collections.abc import Callable

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.async_job import (
    AsyncJobFailedError,
    AsyncJobTimeoutError,
    JobStatus,
    poll_until_done,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import scripted_network

INTERVAL = 15.0
MAX_CHECKS = 100


class _HandedOff(Exception):
    pass


class _VendorTimeoutError(Exception):
    pass


class _VendorFailedError(Exception):
    pass


def _job(statuses: list[JobStatus[str]]) -> tuple[Callable[[], JobStatus[str]], list[JobStatus[str]]]:
    checked: list[JobStatus[str]] = []

    def check() -> JobStatus[str]:
        if len(checked) >= MAX_CHECKS:
            raise AssertionError("The poll did not stop")
        status = statuses[min(len(checked), len(statuses) - 1)]
        checked.append(status)
        return status

    return check, checked


def _pending(message: str = "RUNNING") -> JobStatus[str]:
    return JobStatus(message=message)


@pytest.mark.parametrize(
    "pending_checks,wait_first,expected_waits",
    [
        (0, False, 0),
        (2, False, 2),
        (0, True, 1),
        (2, True, 3),
    ],
)
def test_returns_the_result_once_the_job_is_done(pending_checks: int, wait_first: bool, expected_waits: int) -> None:
    check, checked = _job([*([_pending()] * pending_checks), JobStatus(done=True, result="https://example.com/file")])
    safe_points: list[float] = []

    with scripted_network([]) as network:
        result = poll_until_done(
            check,
            interval=INTERVAL,
            budget_seconds=3600,
            safe_point=lambda: safe_points.append(network.elapsed),
            wait_first=wait_first,
        )

    assert result == "https://example.com/file"
    assert len(checked) == pending_checks + 1
    assert network.elapsed == expected_waits * INTERVAL
    assert safe_points == [index * INTERVAL for index in range(expected_waits)]


@pytest.mark.parametrize(
    "failed_error,expected_error,expected_message",
    [
        (None, AsyncJobFailedError, "The job failed: quota used up"),
        (lambda status: _VendorFailedError(f"Vendor said {status.message}"), _VendorFailedError, "Vendor said quota"),
    ],
)
def test_raises_when_the_job_fails(
    failed_error: Callable[[JobStatus[str]], Exception] | None,
    expected_error: type[Exception],
    expected_message: str,
) -> None:
    check, checked = _job([_pending(), JobStatus(failed=True, message="quota used up")])

    with scripted_network([]) as network, pytest.raises(expected_error, match=expected_message):
        poll_until_done(check, interval=INTERVAL, budget_seconds=3600, failed_error=failed_error)

    assert len(checked) == 2
    assert network.elapsed == INTERVAL


@pytest.mark.parametrize(
    "budget_seconds,wait_first,expected_checks,expected_elapsed",
    [
        (60, False, 5, 60),
        (60, True, 4, 60),
        (50, False, 5, 60),
        (0, False, 1, 0),
    ],
)
@pytest.mark.parametrize(
    "timeout_error,expected_error,expected_message",
    [
        (None, AsyncJobTimeoutError, "The job is still QUEUED after"),
        (lambda status: _VendorTimeoutError(f"still {status.message}"), _VendorTimeoutError, "still QUEUED"),
    ],
)
def test_raises_when_the_budget_is_spent(
    budget_seconds: float,
    wait_first: bool,
    expected_checks: int,
    expected_elapsed: float,
    timeout_error: Callable[[JobStatus[str]], Exception] | None,
    expected_error: type[Exception],
    expected_message: str,
) -> None:
    check, checked = _job([_pending("QUEUED")])

    with scripted_network([]) as network, pytest.raises(expected_error, match=expected_message):
        poll_until_done(
            check,
            interval=INTERVAL,
            budget_seconds=budget_seconds,
            wait_first=wait_first,
            timeout_error=timeout_error,
        )

    assert len(checked) == expected_checks
    assert network.elapsed == expected_elapsed


def test_a_shutdown_during_a_wait_hands_off_at_the_safe_point() -> None:
    check, checked = _job([_pending()])
    shutdown_at = INTERVAL + 5

    with scripted_network([]) as network:

        def is_shutting_down() -> bool:
            return network.elapsed >= shutdown_at

        def safe_point() -> None:
            if is_shutting_down():
                raise _HandedOff

        with (
            activate_safe_point(safe_point, covers_framework_checkpoints=False, is_shutting_down=is_shutting_down),
            pytest.raises(_HandedOff),
        ):
            poll_until_done(check, interval=INTERVAL, budget_seconds=3600, safe_point=safe_point)

    assert len(checked) == 2
    assert network.elapsed == shutdown_at


def test_without_a_safe_point_a_shutdown_shortens_the_waits_and_the_budget_still_ends_the_poll() -> None:
    check, checked = _job([_pending()])

    with (
        scripted_network([]) as network,
        activate_safe_point(lambda: None, covers_framework_checkpoints=False, is_shutting_down=lambda: True),
        pytest.raises(AsyncJobTimeoutError),
    ):
        poll_until_done(check, interval=INTERVAL, budget_seconds=60)

    assert len(checked) == 5
    assert network.elapsed == 0


def test_a_status_cannot_be_done_and_failed() -> None:
    with pytest.raises(ValueError):
        JobStatus(done=True, failed=True)
