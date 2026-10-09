import threading
import contextvars
from collections.abc import Callable
from typing import Any

from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.abandonable_iterate import (
    SourceAbandonedError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    SourceWaitSignals,
    activate_wait_signals,
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.progress import (
    RETRY_WAIT,
    ImportProgress,
    activate_import_progress,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point

# Long enough that a wait which nothing interrupts fails the test on its join timeout.
LONG_WAIT_SECONDS = 60.0
JOIN_TIMEOUT_SECONDS = 5.0


class _HandOff(Exception):
    pass


def _raise_hand_off() -> None:
    raise _HandOff()


class _SourceThread:
    """Runs `work` the way the pipeline runs a source: on a thread that copied the caller's context."""

    def __init__(self, work: Callable[[], Any]) -> None:
        self.error: BaseException | None = None
        self._work = work
        self._thread = threading.Thread(target=contextvars.copy_context().run, args=(self._run,), daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self._work()
        except BaseException as error:
            self.error = error

    def ended(self) -> bool:
        self._thread.join(JOIN_TIMEOUT_SECONDS)
        return not self._thread.is_alive()


def test_outside_an_import_the_wait_is_a_plain_sleep() -> None:
    with patch("time.sleep") as sleep:
        assert interruptible_wait(12.5) is False

    sleep.assert_called_once_with(12.5)


def test_a_wait_counts_as_progress() -> None:
    progress = ImportProgress()

    with activate_import_progress(progress), patch("time.sleep"):
        interruptible_wait(1.0)

    assert progress.snapshot().kind == RETRY_WAIT


def test_a_wait_ends_with_an_error_when_the_pipeline_leaves_the_source() -> None:
    signals = SourceWaitSignals()
    waiting = threading.Event()

    def work() -> None:
        waiting.set()
        interruptible_wait(LONG_WAIT_SECONDS)

    with activate_wait_signals(signals):
        source = _SourceThread(work)
    assert waiting.wait(JOIN_TIMEOUT_SECONDS)
    assert source.error is None

    signals.notify_abandoned()

    assert source.ended()
    assert isinstance(source.error, SourceAbandonedError)


def test_a_wait_reaches_the_safe_point_at_shutdown_and_not_when_the_caller_names_none() -> None:
    shutting_down = threading.Event()
    results: list[bool] = []

    def work() -> None:
        results.append(interruptible_wait(LONG_WAIT_SECONDS))
        interruptible_wait(LONG_WAIT_SECONDS, safe_point=_raise_hand_off)

    with activate_safe_point(
        _raise_hand_off, covers_framework_checkpoints=False, is_shutting_down=shutting_down.is_set
    ):
        shutting_down.set()
        source = _SourceThread(work)

    assert source.ended()
    assert results == [True]
    assert isinstance(source.error, _HandOff)
