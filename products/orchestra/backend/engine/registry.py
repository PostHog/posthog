from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, overload

ExecutionFn = Callable[..., Awaitable[Any]]
StepFn = Callable[..., Awaitable[Any]]

_EXECUTIONS: dict[str, ExecutionFn] = {}
_STEPS: dict[str, StepFn] = {}


@overload
def execution(fn: ExecutionFn) -> ExecutionFn: ...
@overload
def execution(*, name: str) -> Callable[[ExecutionFn], ExecutionFn]: ...
def execution(fn: ExecutionFn | None = None, *, name: str | None = None):  # type: ignore[misc]
    def register(f: ExecutionFn) -> ExecutionFn:
        key = name or f.__name__
        _EXECUTIONS[key] = f
        f.__execution_name__ = key  # type: ignore[attr-defined]
        return f

    if fn is not None:
        return register(fn)
    return register


@overload
def step(fn: StepFn) -> StepFn: ...
@overload
def step(*, name: str) -> Callable[[StepFn], StepFn]: ...
def step(fn: StepFn | None = None, *, name: str | None = None):  # type: ignore[misc]
    def register(f: StepFn) -> StepFn:
        key = name or f.__name__
        _STEPS[key] = f
        f.__step_name__ = key  # type: ignore[attr-defined]
        return f

    if fn is not None:
        return register(fn)
    return register


def get_execution(name: str) -> ExecutionFn:
    try:
        return _EXECUTIONS[name]
    except KeyError as e:
        raise LookupError(f"execution {name!r} is not registered") from e


def get_step(name: str) -> StepFn:
    try:
        return _STEPS[name]
    except KeyError as e:
        raise LookupError(f"step {name!r} is not registered") from e


def step_name(fn_or_name: StepFn | str) -> str:
    if isinstance(fn_or_name, str):
        return fn_or_name
    name = getattr(fn_or_name, "__step_name__", None)
    if name is None:
        raise TypeError(f"{fn_or_name!r} is not registered as a @step")
    return name
