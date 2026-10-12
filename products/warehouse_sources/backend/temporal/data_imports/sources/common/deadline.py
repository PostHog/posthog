import queue
import threading
import contextvars
from collections.abc import Callable, Generator, Iterator
from concurrent.futures import Future
from typing import Any, TypeVar

from django.db import connections

_T = TypeVar("_T")

_EXHAUSTED: Any = object()

# How long the caller waits for the reader thread to close its iterator after a read that ended
# without a deadline. The close releases the connection of the read, so the caller waits for it,
# but not without limit.
ITERATOR_CLOSE_GRACE_SECONDS = 30


class DeadlineExceededError(Exception):
    """The operation gave no answer before its deadline."""

    def __init__(self, timeout_seconds: float) -> None:
        super().__init__(f"No answer within {timeout_seconds:g} seconds")
        self.timeout_seconds = timeout_seconds


def run_with_deadline(operation: Callable[[], _T], *, timeout_seconds: float, thread_name: str) -> _T:
    """Run `operation` and raise `DeadlineExceededError` if it gives no answer in time.

    For a blocking call into a driver that has no timeout of its own. Python cannot stop a thread,
    so the operation runs on a daemon thread and the caller stops waiting at the deadline. The
    caller's thread then returns, which is what lets a Temporal activity finish and a worker shut
    down. The abandoned thread ends when its call returns or when the process exits.

    `operation` must own every resource it uses, because it can still be running after the caller
    has moved on. Do not pass it a connection that the caller also uses.
    """
    outcome: Future[_T] = Future()
    context = contextvars.copy_context()

    def _run() -> None:
        try:
            outcome.set_result(context.run(operation))
        except BaseException as e:
            outcome.set_exception(e)
        finally:
            # Django connections are per thread, and nothing else closes the ones this thread opened.
            connections.close_all()

    thread = threading.Thread(target=_run, name=thread_name, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if not outcome.done():
        raise DeadlineExceededError(timeout_seconds)
    return outcome.result()


def iterate_with_deadline(
    make_iterator: Callable[[], Iterator[_T]],
    *,
    first_item_timeout_seconds: float,
    next_item_timeout_seconds: float,
    thread_name: str,
) -> Generator[_T]:
    """Yield the items of `make_iterator()`, and raise `DeadlineExceededError` when one does not come in time.

    For a read through a driver that has no timeout of its own. The limits apply to the wait for
    one item, not to the read as a whole, so a long read that keeps giving items never reaches
    them. The first item has its own limit because it includes the connect and the query.

    The iterator runs on one daemon thread, and it advances only while the caller waits for the
    next item. Code around each `yield` of the iterator thus runs in the same order, relative to
    the caller, as it does without this wrapper.

    At a deadline the caller stops waiting, and the thread stays in its driver call. When that
    call returns, the thread closes the iterator. `make_iterator` must own every resource that
    the iterator uses.
    """
    next_requests: queue.SimpleQueue[bool] = queue.SimpleQueue()
    outcomes: queue.SimpleQueue[Future[_T]] = queue.SimpleQueue()
    context = contextvars.copy_context()

    def _read() -> None:
        iterator: Iterator[_T] | None = None
        try:
            while next_requests.get():
                outcome: Future[_T] = Future()
                try:
                    if iterator is None:
                        iterator = make_iterator()
                    outcome.set_result(next(iterator, _EXHAUSTED))
                except BaseException as e:
                    outcome.set_exception(e)
                outcomes.put(outcome)
        finally:
            close = getattr(iterator, "close", None)
            try:
                if close is not None:
                    close()
            finally:
                # Django connections are per thread, and nothing else closes the ones this thread opened.
                connections.close_all()

    thread = threading.Thread(target=context.run, args=(_read,), name=thread_name, daemon=True)
    thread.start()
    abandoned = False
    timeout_seconds = first_item_timeout_seconds
    try:
        while True:
            next_requests.put(True)
            try:
                outcome = outcomes.get(timeout=timeout_seconds)
            except queue.Empty:
                abandoned = True
                raise DeadlineExceededError(timeout_seconds) from None
            item = outcome.result()
            if item is _EXHAUSTED:
                return
            yield item
            timeout_seconds = next_item_timeout_seconds
    finally:
        next_requests.put(False)
        if not abandoned:
            thread.join(ITERATOR_CLOSE_GRACE_SECONDS)
