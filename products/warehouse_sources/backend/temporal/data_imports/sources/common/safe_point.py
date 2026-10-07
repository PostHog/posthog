"""Safe points: places in a resumable source where the run can stop and resume without losing rows.

A resumable source stages its cursor with `ResumableSourceManager.save_state`, and the pipeline
commits the cursor after it writes the rows that the cursor covers. The pipeline also checks for a
worker shutdown, but only when the source yields an item. A source that makes many requests that
return no rows (an empty delta page, a parent with no children) yields nothing for a long time. It
then never sees the shutdown, and it never commits its cursor, so it holds the worker until the
graceful shutdown timeout ends and restarts from its last commit.

A safe point closes that gap. The pipeline installs a hook for the length of the extraction, and a
source calls `reach_safe_point()` (or `ResumableSourceManager.safe_point()`) where resuming from the
staged cursor loses no rows: every row the cursor covers has already been yielded to the pipeline,
and the source holds none of those rows in a local buffer. The hook can raise
`WorkerShuttingDownError`, which the pipeline handles the same way as a shutdown it detects itself,
and it can commit the staged cursor when nothing is waiting to be written.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from posthog.dataclasses import frozen

SafePointHook = Callable[[], None]


@frozen
class _ActiveSafePoint:
    hook: SafePointHook
    # The shared REST framework reaches a safe point after each page it hands on. That is only safe
    # when the framework's own generator is what the pipeline iterates. A source that wraps it could
    # buffer rows between the two, and the framework cannot see that buffer.
    covers_framework_checkpoints: bool


_active_safe_point: ContextVar[_ActiveSafePoint | None] = ContextVar("warehouse_source_safe_point", default=None)
_safe_points_held: ContextVar[bool] = ContextVar("warehouse_source_safe_points_held", default=False)


@contextmanager
def activate_safe_point(hook: SafePointHook, *, covers_framework_checkpoints: bool) -> Iterator[None]:
    """Install `hook` for code that runs in this context, including source threads started in it."""
    token = _active_safe_point.set(
        _ActiveSafePoint(hook=hook, covers_framework_checkpoints=covers_framework_checkpoints)
    )
    try:
        yield
    finally:
        _active_safe_point.reset(token)


@contextmanager
def hold_safe_points() -> Iterator[None]:
    """Make safe points do nothing inside the block.

    The REST framework stages a page's cursor before it hands the page on. A resume hook that
    reaches a safe point would then let the pipeline commit a cursor for rows it does not have yet.
    """
    token = _safe_points_held.set(True)
    try:
        yield
    finally:
        _safe_points_held.reset(token)


def reach_safe_point() -> None:
    """Tell the pipeline that the source is at a safe point. Does nothing outside an extraction."""
    active = _active_safe_point.get()
    if active is not None and not _safe_points_held.get():
        active.hook()


def framework_checkpoints_are_covered() -> bool:
    """Whether the pipeline iterates the REST framework's own generator, with no source wrapper around it."""
    active = _active_safe_point.get()
    return active is not None and active.covers_framework_checkpoints


def reach_framework_safe_point() -> None:
    """The REST framework's safe point, which applies only when nothing wraps the framework's output."""
    if framework_checkpoints_are_covered():
        reach_safe_point()
