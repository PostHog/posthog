import threading
import contextvars
from collections.abc import Generator, Iterator

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.deadline import (
    DeadlineExceededError,
    iterate_with_deadline,
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


def _iterate(make_iterator, *, first: float = 5, following: float = 5) -> Generator:
    return iterate_with_deadline(
        make_iterator, first_item_timeout_seconds=first, next_item_timeout_seconds=following, thread_name="reader"
    )


def test_iterator_advances_only_while_the_caller_waits_for_the_next_item() -> None:
    # A read that ran ahead of the caller would stage a resume checkpoint for a batch that the
    # caller did not take yet.
    events: list[str] = []
    _REQUEST_ID.set("from-caller")

    def _read() -> Iterator[int]:
        for item in range(3):
            events.append(f"read {item} for {_REQUEST_ID.get()}")
            yield item
        events.append("end")

    for item in _iterate(_read):
        events.append(f"took {item}")

    assert events == [
        "read 0 for from-caller",
        "took 0",
        "read 1 for from-caller",
        "took 1",
        "read 2 for from-caller",
        "took 2",
        "end",
    ]


def test_iterator_error_reaches_the_caller_after_the_items_before_it() -> None:
    def _read() -> Iterator[int]:
        yield 1
        raise TimeoutError("driver timeout")

    taken: list[int] = []
    with pytest.raises(TimeoutError, match="driver timeout"):
        for item in _iterate(_read):
            taken.append(item)

    assert taken == [1]


@pytest.mark.parametrize(
    "items_before_the_hang, expected_timeout",
    [(0, 0.05), (2, 0.07)],
    ids=["first_item", "later_item"],
)
def test_a_silent_iterator_raises_at_the_deadline_and_is_closed_when_its_call_returns(
    items_before_the_hang: int, expected_timeout: float
) -> None:
    release = threading.Event()
    closed = threading.Event()

    def _read() -> Iterator[int]:
        try:
            yield from range(items_before_the_hang)
            release.wait()
            yield -1
        finally:
            closed.set()

    taken: list[int] = []
    try:
        with pytest.raises(DeadlineExceededError) as error:
            for item in _iterate(_read, first=0.05, following=0.07):
                taken.append(item)
        assert not closed.is_set()
    finally:
        release.set()

    assert taken == list(range(items_before_the_hang))
    assert error.value.timeout_seconds == expected_timeout
    assert closed.wait(5)


def test_a_caller_that_stops_early_closes_the_iterator() -> None:
    closed = threading.Event()

    def _read() -> Iterator[int]:
        try:
            yield from range(10)
        finally:
            closed.set()

    items = _iterate(_read)
    assert next(items) == 0
    items.close()

    assert closed.is_set()
