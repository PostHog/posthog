import threading
import contextvars
from collections.abc import Callable
from concurrent.futures import Future
from typing import TypeVar

from django.db import connections

_T = TypeVar("_T")


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
