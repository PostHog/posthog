"""Progress of one import attempt, reported by the code that does the work.

The import activity sends its Temporal heartbeats from a timer on the event loop. The timer runs
while a source thread is blocked in a call that never returns, so the heartbeat alone says nothing
about the import. `ImportProgress` records the last time the attempt did something that only a
live import does: the source yielded an item, staged a checkpoint, reached a safe point, completed
a request, or the pipeline wrote a batch. The activity reads the record to decide whether the
attempt still makes progress.

The activity installs one `ImportProgress` for the attempt. Threads that start inside the attempt
copy the context, so a source reports to the same record from its own thread.
"""

import sys
import time
import functools
import threading
import traceback
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import ParamSpec, TypeVar

from posthog.dataclasses import frozen
from posthog.temporal.common.errors import NonReportableError

_P = ParamSpec("_P")
_T = TypeVar("_T")

ATTEMPT_STARTED = "attempt_started"
SOURCE_ITEM = "source_item"
BATCH_WRITTEN = "batch_written"
SAFE_POINT = "safe_point"
CHECKPOINT_STAGED = "checkpoint_staged"
SOURCE_REQUEST = "source_request"
RETRY_WAIT = "retry_wait"

# The innermost frames of a blocked thread name the call it waits in. More frames add only the
# pipeline code that every import shares.
BLOCKED_THREAD_FRAME_LIMIT = 12


class ImportStalledError(NonReportableError):
    """The attempt made no progress for longer than its limit, and its heartbeats stopped.

    Temporal ends an attempt that stops its heartbeats, and starts the next attempt on another
    worker. Work that continues here after that would write next to the new attempt.
    """


@frozen
class ProgressSnapshot:
    kind: str
    seconds_since_progress: float
    # False until the source yields its first item in this attempt.
    source_item_seen: bool


class ImportProgress:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._last_progress_at = clock()
        self._kind = ATTEMPT_STARTED
        self._source_item_seen = False
        self._stalled = False
        self._watched_threads: dict[int, int] = {}
        self._stall_callbacks: list[Callable[[], None]] = []

    def record(self, kind: str) -> None:
        with self._lock:
            self._last_progress_at = self._clock()
            self._kind = kind
            if kind == SOURCE_ITEM:
                self._source_item_seen = True

    def snapshot(self) -> ProgressSnapshot:
        with self._lock:
            return ProgressSnapshot(
                kind=self._kind,
                seconds_since_progress=self._clock() - self._last_progress_at,
                source_item_seen=self._source_item_seen,
            )

    @property
    def is_stalled(self) -> bool:
        return self._stalled

    def mark_stalled(self) -> None:
        """Make the stall permanent for this attempt. Later progress does not clear it."""
        self._stalled = True

    def on_stall(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._stall_callbacks.append(callback)

    def run_stall_callbacks(self) -> list[BaseException]:
        """Run every callback, also after one fails. Returns the errors."""
        with self._lock:
            callbacks = list(self._stall_callbacks)
        errors: list[BaseException] = []
        for callback in callbacks:
            try:
                callback()
            except Exception as error:
                errors.append(error)
        return errors

    @contextmanager
    def watching_current_thread(self) -> Iterator[None]:
        """Name the current thread as one that works for the attempt, for `blocked_thread_frames`."""
        thread_id = threading.get_ident()
        with self._lock:
            self._watched_threads[thread_id] = self._watched_threads.get(thread_id, 0) + 1
        try:
            yield
        finally:
            with self._lock:
                depth = self._watched_threads.get(thread_id, 0) - 1
                if depth > 0:
                    self._watched_threads[thread_id] = depth
                else:
                    self._watched_threads.pop(thread_id, None)

    def watched(self, function: Callable[_P, _T]) -> Callable[_P, _T]:
        """Wrap `function` so that the thread it runs on is watched for the length of the call."""

        @functools.wraps(function)
        def call(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            with self.watching_current_thread():
                return function(*args, **kwargs)

        return call

    def blocked_thread_frames(self, limit: int = BLOCKED_THREAD_FRAME_LIMIT) -> dict[str, list[str]]:
        """Where each watched thread is now: file, line and function name, the innermost frame first.

        The values of local variables can hold credentials and customer rows, so no frame content
        other than its position is read.
        """
        with self._lock:
            thread_ids = list(self._watched_threads)
        if not thread_ids:
            return {}
        frames = sys._current_frames()
        names = {thread.ident: thread.name for thread in threading.enumerate()}
        positions: dict[str, list[str]] = {}
        for thread_id in thread_ids:
            frame = frames.get(thread_id)
            if frame is None:
                continue
            summary = traceback.StackSummary.extract(traceback.walk_stack(frame), limit=limit, lookup_lines=False)
            positions[names.get(thread_id) or str(thread_id)] = [
                f"{entry.filename}:{entry.lineno} in {entry.name}" for entry in summary
            ]
        return positions


_active_progress: ContextVar[ImportProgress | None] = ContextVar("warehouse_import_progress", default=None)


@contextmanager
def activate_import_progress(progress: ImportProgress) -> Iterator[None]:
    """Install `progress` for code that runs in this context, including threads started in it."""
    token = _active_progress.set(progress)
    try:
        yield
    finally:
        _active_progress.reset(token)


def current_import_progress() -> ImportProgress | None:
    return _active_progress.get()


def note_progress(kind: str) -> None:
    """Record that the import did something now. Does nothing outside an import attempt."""
    progress = _active_progress.get()
    if progress is not None:
        progress.record(kind)


def raise_if_import_stalled() -> None:
    progress = _active_progress.get()
    if progress is not None and progress.is_stalled:
        raise ImportStalledError(
            "The import made no progress for longer than its limit, so its heartbeats stopped and "
            "Temporal started another attempt. This attempt stops here."
        )


class _WatchedIterator(Iterator[_T]):
    """Watches the thread that runs each `next()` of a source."""

    def __init__(self, iterator: Iterator[_T], progress: ImportProgress) -> None:
        self._iterator = iterator
        self._progress = progress

    def __iter__(self) -> "_WatchedIterator[_T]":
        return self

    def __next__(self) -> _T:
        with self._progress.watching_current_thread():
            return next(self._iterator)

    def close(self) -> None:
        close = getattr(self._iterator, "close", None)
        if callable(close):
            close()


def watch_source_threads(items: Iterable[_T]) -> Iterable[_T]:
    """Return `items` in a form that tells the active `ImportProgress` which thread reads the source.

    An async source runs on the event loop and has no thread of its own, so the caller must pass
    only a sync iterable.
    """
    progress = _active_progress.get()
    if progress is None:
        return items
    return _WatchedIterator(iter(items), progress)
