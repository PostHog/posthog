"""Timing hooks that callers inject into the transformers.

A caller passes a factory that builds a recorder for each timed block. Without a factory,
the transformers record nothing.
"""

import types
import typing


class ExecutionTimeRecorder(typing.Protocol):
    """A context manager that times its block and counts the bytes it processed."""

    def __enter__(self) -> typing.Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None: ...

    def add_bytes_processed(self, bytes_processed: int) -> int: ...


class ExecutionTimeRecorderFactory(typing.Protocol):
    """Build an `ExecutionTimeRecorder` for one timed block."""

    def __call__(
        self,
        histogram_name: str,
        /,
        *,
        description: str | None = ...,
        log_message: str = ...,
        log_attributes: dict[str, typing.Any] | None = ...,
    ) -> ExecutionTimeRecorder: ...


class NoOpExecutionTimeRecorder:
    """An `ExecutionTimeRecorder` that records nothing."""

    def __init__(
        self,
        histogram_name: str,
        /,
        *,
        description: str | None = None,
        log_message: str = "",
        log_attributes: dict[str, typing.Any] | None = None,
    ) -> None:
        self.bytes_processed = 0

    def __enter__(self) -> typing.Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        return None

    def add_bytes_processed(self, bytes_processed: int) -> int:
        self.bytes_processed += bytes_processed
        return self.bytes_processed
