import functools
from collections.abc import Awaitable, Callable
from inspect import iscoroutinefunction
from typing import Any, Literal, ParamSpec, TypeVar, overload

from temporalio import workflow

P = ParamSpec("P")
R = TypeVar("R")

LogLevel = Literal["debug", "info", "warning", "error", "exception"]


class log_on_fail:
    """Decorator that logs and optionally swallows exceptions from the wrapped callable.

    Catches `Exception` only — `asyncio.CancelledError` propagates through,
    which matches what Temporal workflow code wants for cancellation.

    Args:
        message: Log message prefix; the formatted exception is appended.
        level: Logger method to call (`warning`, `error`, ...).
        suppress: If True, log and return None instead of re-raising — for
            best-effort activity wrappers where the caller doesn't care
            about failure beyond a log line.
    """

    @overload
    def __init__(self, message: str, *, level: LogLevel = ..., suppress: Literal[False] = False) -> None: ...

    @overload
    def __init__(self, message: str, *, suppress: Literal[True], level: LogLevel = ...) -> None: ...

    def __init__(self, message: str, *, level: LogLevel = "error", suppress: bool = False) -> None:
        self.message = message
        self.level = level
        self.suppress = suppress

    @overload
    def __call__(self, fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R | None]]: ...

    @overload
    def __call__(self, fn: Callable[P, R]) -> Callable[P, R | None]: ...

    def __call__(self, fn: Callable[P, Any]) -> Callable[P, Any]:
        if iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def awrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                try:
                    return await fn(*args, **kwargs)
                except Exception as e:
                    self._log(e)
                    if self.suppress:
                        return None
                    raise

            return awrapper

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                self._log(e)
                if self.suppress:
                    return None
                raise

        return wrapper

    def _log(self, error: Exception) -> None:
        getattr(workflow.logger, self.level)(f"{self.message}: {error}")
