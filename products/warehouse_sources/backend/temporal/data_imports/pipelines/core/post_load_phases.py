"""Duration and peak process RSS for each post-load phase of one final batch.

The loader opens one recorder for each final batch with ``record_post_load_phases``. Code on the
post-load path marks its steps with ``post_load_phase`` or ``recorded_phase``. These do nothing when
no recorder is active, so the same code runs unchanged on the pre-write path.
When the batch completes, the recorder writes one log line that lists every phase.

The recorder is observability only. An error inside it is logged at debug and never reaches the load.
"""

from __future__ import annotations

import time
import functools
import contextlib
from collections.abc import Awaitable, Callable, Coroutine, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, ParamSpec, TypeVar

import structlog

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.rss_sampler import (
    RssPeakSampler,
    RssWindow,
)

SUMMARY_EVENT = "post_load_phase_rss"
#: Phases past this count are only counted, so a loop that opens phases cannot grow the log line.
MAX_PHASES = 64

P = ParamSpec("P")
T = TypeVar("T")

_LOGGER = structlog.get_logger(__name__)

_ACTIVE: ContextVar[PostLoadPhaseRecorder | None] = ContextVar("post_load_phase_recorder", default=None)


# Identity equality: two phases with the same name and readings are still different phases.
@dataclass(frozen=False, eq=False)
class PhaseRecord:
    name: str
    parent: str | None
    started: float
    duration_ms: int | None = None
    window: RssWindow | None = None
    error: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    has_children: bool = False
    exit_stack: contextlib.ExitStack | None = field(default=None, repr=False)

    def rss_fields(self) -> dict[str, Any]:
        window = self.window
        return {
            "rss_start_mb": window.start_mb if window is not None else None,
            "peak_rss_mb": window.peak_mb if window is not None else None,
            "rss_delta_peak_mb": window.delta_mb if window is not None else None,
            "concurrent_windows_max": window.max_concurrent if window is not None else None,
        }

    def to_log(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"name": self.name, "duration_ms": self.duration_ms, **self.rss_fields()}
        if self.parent is not None:
            entry["parent"] = self.parent
        if self.error is not None:
            entry["error"] = self.error
        for key, value in self.facts.items():
            entry.setdefault(key, value)
        return entry


class PostLoadPhaseRecorder:
    """Records the phases of one final batch, in the order they start.

    Each phase opens its own sampler window. All windows of one recorder share one sampler group,
    so a nested phase does not count as concurrent work. ``concurrent_windows_max`` above 1 means
    another load or upsert in this process was sampled at the same time, so the RSS peak is not
    this phase's alone.
    """

    def __init__(self, sampler: RssPeakSampler | None, clock: Callable[[], float] = time.monotonic) -> None:
        self._sampler = sampler
        self._clock = clock
        self._phases: list[PhaseRecord] = []
        self._open: list[PhaseRecord] = []
        self._dropped = 0
        self._total: PhaseRecord | None = None

    @property
    def phases(self) -> list[PhaseRecord]:
        return list(self._phases)

    def _begin(self, name: str, parent: str | None) -> PhaseRecord:
        record = PhaseRecord(name=name, parent=parent, started=self._clock())
        if self._sampler is not None:
            record.exit_stack = contextlib.ExitStack()
            record.window = record.exit_stack.enter_context(self._sampler.window(group=self))
        return record

    def _end(self, record: PhaseRecord) -> None:
        record.duration_ms = round((self._clock() - record.started) * 1000)
        if record.exit_stack is not None:
            record.exit_stack.close()
            record.exit_stack = None

    def start(self) -> None:
        """Open the window that covers the whole post-load, gaps between phases included."""
        try:
            if self._total is None:
                self._total = self._begin("total", None)
        except Exception:
            _LOGGER.debug("post_load_phase_recorder_failed", step="start", exc_info=True)

    def _start_phase(self, name: str) -> PhaseRecord | None:
        try:
            if len(self._phases) >= MAX_PHASES:
                self._dropped += 1
                return None
            parent = self._open[-1] if self._open else None
            record = self._begin(name, parent.name if parent is not None else None)
            if parent is not None:
                parent.has_children = True
            self._phases.append(record)
            self._open.append(record)
            return record
        except Exception:
            _LOGGER.debug("post_load_phase_recorder_failed", step="start_phase", phase=name, exc_info=True)
            return None

    def _finish_phase(self, record: PhaseRecord | None, error: BaseException | None) -> None:
        if record is None:
            return
        try:
            if record in self._open:
                self._open.remove(record)
            if error is not None:
                record.error = type(error).__name__
            self._end(record)
        except Exception:
            _LOGGER.debug("post_load_phase_recorder_failed", step="finish_phase", phase=record.name, exc_info=True)

    @contextlib.contextmanager
    def phase(self, name: str) -> Iterator[None]:
        record = self._start_phase(name)
        try:
            yield
        except BaseException as e:
            self._finish_phase(record, e)
            raise
        self._finish_phase(record, None)

    def note(self, **facts: Any) -> None:
        """Attach size facts to the innermost open phase, or to the whole post-load outside a phase."""
        try:
            target = self._open[-1] if self._open else self._total
            if target is not None:
                target.facts.update(facts)
        except Exception:
            _LOGGER.debug("post_load_phase_recorder_failed", step="note", exc_info=True)

    def finish(self) -> dict[str, Any]:
        """Close every open window and return the summary fields for the log line."""
        for record in reversed(list(self._open)):
            self._finish_phase(record, None)
        total = self._total
        if total is not None and total.exit_stack is not None:
            self._end(total)
        phases = [record.to_log() for record in self._phases]
        # A parent phase's peak includes its children's, so only leaf phases can name the culprit.
        deltas = [
            (record.window.delta_mb, record.name)
            for record in self._phases
            if not record.has_children and record.window is not None and record.window.delta_mb is not None
        ]
        summary: dict[str, Any] = {
            "phases": phases,
            "phase_names": [p["name"] for p in phases],
            "rss_sampling": self._sampler is not None,
            "total_duration_ms": total.duration_ms if total is not None else None,
            **(total.rss_fields() if total is not None else {}),
            "peak_phase": max(deltas)[1] if deltas else None,
        }
        if total is not None:
            for key, value in total.facts.items():
                summary.setdefault(key, value)
        if self._dropped:
            summary["phases_dropped"] = self._dropped
        return summary


@contextlib.contextmanager
def record_post_load_phases(
    logger: Any, sampler: RssPeakSampler | None, **log_fields: Any
) -> Iterator[PostLoadPhaseRecorder | None]:
    """Record the post-load phases run inside this block and log one ``post_load_phase_rss`` line.

    The line is logged when the block raises too, with ``outcome`` set to the exception type. A
    process that the kernel kills for memory logs nothing, so the line shows a peak only when the
    pod survives it.
    """
    recorder: PostLoadPhaseRecorder | None = None
    token = None
    try:
        recorder = PostLoadPhaseRecorder(sampler)
        recorder.start()
        token = _ACTIVE.set(recorder)
    except Exception:
        _LOGGER.debug("post_load_phase_recorder_failed", step="open", exc_info=True)

    outcome = "ok"
    try:
        yield recorder
    except BaseException as e:
        outcome = type(e).__name__
        raise
    finally:
        try:
            if token is not None:
                _ACTIVE.reset(token)
            if recorder is not None:
                logger.info(SUMMARY_EVENT, **{**recorder.finish(), **log_fields, "outcome": outcome})
        except Exception:
            _LOGGER.debug("post_load_phase_recorder_failed", step="close", exc_info=True)


def active_post_load_recorder() -> PostLoadPhaseRecorder | None:
    return _ACTIVE.get()


@contextlib.contextmanager
def post_load_phase(name: str) -> Iterator[None]:
    """Record the block as a post-load phase. A no-op outside ``record_post_load_phases``."""
    recorder = _ACTIVE.get()
    if recorder is None:
        yield
        return
    with recorder.phase(name):
        yield


def note_post_load_phase(**facts: Any) -> None:
    """Attach size facts to the current post-load phase. A no-op outside ``record_post_load_phases``."""
    recorder = _ACTIVE.get()
    if recorder is not None:
        recorder.note(**facts)


def recorded_phase(name: str) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Coroutine[Any, Any, T]]]:
    """Decorate an async function so each call is recorded as the post-load phase ``name``."""

    def decorate(fn: Callable[P, Awaitable[T]]) -> Callable[P, Coroutine[Any, Any, T]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            with post_load_phase(name):
                return await fn(*args, **kwargs)

        return wrapper

    return decorate
