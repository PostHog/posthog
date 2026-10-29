"""Reads one Shopify object with several requests in flight, each over its own range of `updated_at`.

One paged read sends a request only after the one before it answers, because each page needs the
cursor of the last. A large store can serve more than that: the read uses a fraction of the store's
query cost budget. This reader splits the time range into windows and reads several windows at once.

Shopify returns each window sorted by `updated_at`, so a window that has read up to a time can hand
the rest of its range to another window. When a worker is free, the reader splits the window with the
most time left. A range that holds many rows is split again and again until every worker has work.
"""

import queue
import threading
import contextvars
import dataclasses
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

from posthog.dataclasses import frozen

PARALLEL_READ_WORKERS = 3
# A range shorter than this is not split. Shopify filters on whole seconds.
_MIN_SPLIT = timedelta(seconds=2)
_QUEUE_POLL_SECONDS = 1.0


@dataclasses.dataclass(frozen=False)
class ReadWindow:
    """A range of `updated_at` that one request chain reads.

    The query covers `lo` to `query_hi`. After a split the window stops at `stop_hi` and leaves the
    rest to the new window, but it keeps its query, because its cursor belongs to that query.
    """

    lo: datetime
    query_hi: datetime
    stop_hi: datetime
    # The cursor after the last page the pipeline received, or None before the first page.
    cursor: str | None = None
    done: bool = False
    # The newest `updated_at` a worker has fetched. A split only happens above it.
    progress: datetime | None = None

    def to_state(self) -> dict[str, Any]:
        return {
            "lo": self.lo.isoformat(),
            "query_hi": self.query_hi.isoformat(),
            "stop_hi": self.stop_hi.isoformat(),
            "cursor": self.cursor,
            "done": self.done,
            "progress": self.progress.isoformat() if self.progress is not None else None,
        }

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "ReadWindow":
        progress = state.get("progress")
        return cls(
            lo=datetime.fromisoformat(state["lo"]),
            query_hi=datetime.fromisoformat(state["query_hi"]),
            stop_hi=datetime.fromisoformat(state["stop_hi"]),
            cursor=state.get("cursor"),
            done=bool(state.get("done")),
            # A resumed window splits above the rows it already handed over, not from `lo`.
            progress=datetime.fromisoformat(progress) if progress else None,
        )


@frozen
class FetchedPage:
    rows: list[dict[str, Any]]
    # None when this is the last page of the window's query.
    next_cursor: str | None


@frozen
class _WindowPage:
    window: ReadWindow
    rows: list[dict[str, Any]]
    finished: bool
    next_cursor: str | None
    error: BaseException | None = None


# Reads the pages of one window, from its cursor, and owns the session it uses. It stops asking
# Shopify for pages once the given event is set, so a stopped read does not keep spending the
# store's query budget against the run that replaces it.
FetchWindowPages = Callable[[ReadWindow, threading.Event], Iterator[FetchedPage]]


def _split(windows: list[ReadWindow], active: list[ReadWindow]) -> ReadWindow | None:
    """Give half of the remaining range of the busiest active window to a new window."""
    best: ReadWindow | None = None
    best_span = _MIN_SPLIT
    for window in active:
        span = window.stop_hi - (window.progress or window.lo)
        if span >= best_span:
            best, best_span = window, span
    if best is None:
        return None
    start = best.progress or best.lo
    # A whole-second boundary, because Shopify compares `updated_at` at that precision.
    middle = (start + best_span / 2).replace(microsecond=0)
    if middle <= start:
        return None
    new_window = ReadWindow(lo=middle, query_hi=best.stop_hi, stop_hi=best.stop_hi)
    best.stop_hi = middle
    windows.append(new_window)
    return new_window


def _next_page(pages: "queue.Queue[_WindowPage]", tasks: list[Future[None]]) -> _WindowPage:
    """The next page from the workers. A worker that died without handing over its error fails the read."""
    while True:
        try:
            return pages.get(timeout=_QUEUE_POLL_SECONDS)
        except queue.Empty:
            for task in tasks:
                error = task.exception() if task.done() else None
                if error is not None:
                    raise error


def read_windows(
    windows: list[ReadWindow],
    fetch_pages: FetchWindowPages,
    row_time: Callable[[dict[str, Any]], datetime],
    save_windows: Callable[[list[dict[str, Any]]], None],
    safe_point: Callable[[], None],
    workers: int = PARALLEL_READ_WORKERS,
) -> Iterator[list[dict[str, Any]]]:
    """Yield the rows of every window, reading up to `workers` windows at once.

    Rows come in the order the windows answer, not in `updated_at` order. `save_windows` receives
    the state of every window before each page goes to the pipeline, so a resume reads each window
    from the cursor after the last page the pipeline received.
    """
    lock = threading.Lock()
    pages: queue.Queue[_WindowPage] = queue.Queue(maxsize=workers * 2)
    stop = threading.Event()

    def hand_over(page: _WindowPage) -> None:
        while not stop.is_set():
            try:
                pages.put(page, timeout=_QUEUE_POLL_SECONDS)
                return
            except queue.Full:
                continue

    def read(window: ReadWindow) -> None:
        try:
            for fetched in fetch_pages(window, stop):
                with lock:
                    # Rows are sorted by `updated_at`, so the first row at or above the stop ends
                    # the window. A split can lower the stop while this page is in flight.
                    kept = [row for row in fetched.rows if row_time(row) < window.stop_hi]
                    finished = fetched.next_cursor is None or len(kept) < len(fetched.rows)
                    if kept:
                        window.progress = row_time(kept[-1])
                hand_over(_WindowPage(window=window, rows=kept, finished=finished, next_cursor=fetched.next_cursor))
                if finished or stop.is_set():
                    return
            hand_over(_WindowPage(window=window, rows=[], finished=True, next_cursor=None))
        except BaseException as error:
            hand_over(_WindowPage(window=window, rows=[], finished=False, next_cursor=None, error=error))

    pending = [window for window in windows if not window.done]
    active: list[ReadWindow] = []
    tasks: list[Future[None]] = []
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="shopify-window")
    try:
        while True:
            with lock:
                while len(active) < workers:
                    window = pending.pop(0) if pending else _split(windows, active)
                    if window is None:
                        break
                    active.append(window)
                    # A copy of the context keeps the job's log and request tracking in the worker.
                    tasks.append(executor.submit(contextvars.copy_context().run, read, window))
            if not active:
                return
            page = _next_page(pages, tasks)
            if page.error is not None:
                raise page.error
            with lock:
                if page.finished:
                    page.window.done = True
                    active.remove(page.window)
                else:
                    page.window.cursor = page.next_cursor
                state = [window.to_state() for window in windows]
            save_windows(state)
            if page.rows:
                yield page.rows
            else:
                # An empty page leaves no row in the reader, so the run can stop and resume here.
                safe_point()
    finally:
        stop.set()
        while not pages.empty():
            pages.get_nowait()
        executor.shutdown(wait=False, cancel_futures=True)
