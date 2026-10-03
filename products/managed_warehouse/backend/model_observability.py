from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from types import FrameType
from typing import TYPE_CHECKING

from django.db import models

from posthog.dataclasses import frozen

from products.managed_warehouse.backend.metrics import record_counter

if TYPE_CHECKING:
    from products.managed_warehouse.backend.models import DuckgresServer


DUCKGRES_SERVER_ACCESS_METRIC = "warehouse.duckgres.server.model.access"

_access_recording_suppressed: ContextVar[bool] = ContextVar(
    "duckgres_server_access_recording_suppressed", default=False
)
_INTERNAL_CALLER_MODULES = {
    __name__,
    "products.managed_warehouse.backend.models",
}
_CALLER_GATEWAY_MODULES = {
    "products.managed_warehouse.backend.common",
    "products.managed_warehouse.backend.facade.api",
    "products.managed_warehouse.backend.logic.connection",
}
_FRAMEWORK_CALLER_PREFIXES = (
    "asgiref.",
    "concurrent.futures.",
    "django.",
    "threading",
)
_MAX_CALLER_NAME_LENGTH = 160


@frozen
class _CallerAttribution:
    accessor_module: str
    accessor_function: str
    caller_module: str
    caller_function: str


def _caller_name(value: str) -> str:
    return (value or "unknown")[:_MAX_CALLER_NAME_LENGTH]


def _external_callers() -> _CallerAttribution:
    frame: FrameType | None = sys._getframe(1)
    accessor: tuple[str, str] | None = None
    while frame is not None:
        module = str(frame.f_globals.get("__name__", ""))
        if module not in _INTERNAL_CALLER_MODULES and not module.startswith(_FRAMEWORK_CALLER_PREFIXES):
            current = (_caller_name(module), _caller_name(frame.f_code.co_name))
            accessor = accessor or current
            if module not in _CALLER_GATEWAY_MODULES:
                return _CallerAttribution(
                    accessor_module=accessor[0],
                    accessor_function=accessor[1],
                    caller_module=current[0],
                    caller_function=current[1],
                )
        frame = frame.f_back
    unknown = ("unknown", "unknown")
    accessor = accessor or unknown
    return _CallerAttribution(
        accessor_module=accessor[0],
        accessor_function=accessor[1],
        caller_module=accessor[0],
        caller_function=accessor[1],
    )


def record_duckgres_server_access(operation: str) -> None:
    if _access_recording_suppressed.get():
        return

    attribution = _external_callers()
    try:
        record_counter(
            DUCKGRES_SERVER_ACCESS_METRIC,
            1,
            {
                "operation": operation,
                "accessor_module": attribution.accessor_module,
                "accessor_function": attribution.accessor_function,
                "caller_module": attribution.caller_module,
                "caller_function": attribution.caller_function,
            },
        )
    except Exception:
        # Access telemetry must never make a model operation fail.
        pass


@contextmanager
def suppress_duckgres_server_access_recording() -> Iterator[None]:
    token = _access_recording_suppressed.set(True)
    try:
        yield
    finally:
        _access_recording_suppressed.reset(token)


class DuckgresServerQuerySet(models.QuerySet["DuckgresServer"]):
    def _fetch_all(self) -> None:
        if self._result_cache is None:
            record_duckgres_server_access("read")
        super()._fetch_all()

    def count(self) -> int:
        record_duckgres_server_access("read")
        return super().count()

    def exists(self) -> bool:
        record_duckgres_server_access("read")
        return super().exists()

    def iterator(self, chunk_size: int | None = None) -> Iterator[DuckgresServer]:
        record_duckgres_server_access("read")
        return super().iterator(chunk_size=chunk_size)

    def update(self, **kwargs: object) -> int:
        record_duckgres_server_access("update")
        return super().update(**kwargs)

    def delete(self) -> tuple[int, dict[str, int]]:
        record_duckgres_server_access("delete")
        with suppress_duckgres_server_access_recording():
            return super().delete()


DuckgresServerManager = models.Manager.from_queryset(DuckgresServerQuerySet)
