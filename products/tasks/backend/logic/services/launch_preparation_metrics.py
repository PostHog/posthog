from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from typing import Literal

from temporalio.activity import metric_meter

_launch_preparation_attributes: ContextVar[dict[str, str] | None] = ContextVar(
    "launch_preparation_attributes", default=None
)


@contextmanager
def launch_preparation_metric_context(
    *, boot_path: str, runtime: str, origin_product: str | None, used_snapshot: bool | None
) -> Iterator[None]:
    token = _launch_preparation_attributes.set(
        {
            "boot_path": boot_path,
            "runtime": runtime,
            "origin_product": origin_product or "unknown",
            "used_snapshot": "unknown" if used_snapshot is None else str(used_snapshot).lower(),
        }
    )
    try:
        yield
    finally:
        _launch_preparation_attributes.reset(token)


def record_launch_preparation_ms(duration_ms: int, status: Literal["COMPLETED", "FAILED"]) -> None:
    attributes = _launch_preparation_attributes.get()
    if attributes is None:
        return
    try:
        metric_meter().with_additional_attributes({**attributes, "status": status}).create_histogram_timedelta(
            "tasks_modal_launch_preparation_latency",
            "Modal launch file installation and agentsh preparation, including upload",
            unit="ms",
        ).record(timedelta(milliseconds=duration_ms))
    except Exception:
        pass
