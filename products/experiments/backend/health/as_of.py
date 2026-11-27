"""The `as_of` of a check result: the end of the data that the check read.

Most inputs of a `HealthContext` are settings, which the loader reads when the checks run. A few hold data from a time
window that can end hours earlier: the exposure totals of a cached exposure answer, the stored metric results, and the
cached scan of the flag calls. A check that reads one of them is only as current as the end of that window. The
recording below finds which of them each check reads, so a check that reads them only on some branches gets the
earliest end of what it read on this run, and a new check needs no declaration.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import fields
from datetime import datetime

from products.experiments.backend.health.context import (
    ConditionSetTraffic,
    ExposureTotals,
    HealthContext,
    LatestCalculation,
    PrimaryMetric,
)

_WINDOWED_INPUTS = frozenset({"condition_set_traffic", "exposures", "latest_calculation", "primary_metric"})

# A context variable, not an attribute of the context, because a check can build a new context with `replace`, and the
# reads on that context count too.
_read_inputs: ContextVar[list[object] | None] = ContextVar("health_check_read_inputs", default=None)


class _RecordingContext(HealthContext):
    __slots__ = ()

    def __getattribute__(self, name: str) -> object:
        value = super().__getattribute__(name)
        if name in _WINDOWED_INPUTS and value is not None and (read := _read_inputs.get()) is not None:
            read.append(value)
        return value


def recording(ctx: HealthContext) -> HealthContext:
    """`ctx` as a context that records the windowed inputs that a check reads inside `recorded_inputs`."""
    return _RecordingContext(**{field.name: getattr(ctx, field.name) for field in fields(ctx)})


@contextmanager
def recorded_inputs() -> Iterator[list[object]]:
    read: list[object] = []
    token = _read_inputs.set(read)
    try:
        yield read
    finally:
        _read_inputs.reset(token)


def earliest_data_end(read: Sequence[object], checked_at: datetime) -> datetime:
    """The earliest window end of the inputs in `read`, or `checked_at` when the check read only settings."""
    return min((end for value in read if (end := _window_end(value)) is not None), default=checked_at)


def _window_end(value: object) -> datetime | None:
    match value:
        case ConditionSetTraffic():
            return value.until
        case ExposureTotals() | LatestCalculation() | PrimaryMetric():
            return value.data_until
    return None
