"""Where destination writers are looked up by type.

The external destinations (Redshift, Snowflake, BigQuery, ...) are implemented on top of
batch exports' destination clients and transformers, which warehouse_sources depends on
directly (see tach.toml). Writers are still resolved by type string rather than imported at
the call site, so the processor never names a destination type and a driver only loads when
a destination of that type is actually written to.

An unregistered type raises rather than degrading to a no-op: silently writing nothing to a
destination a customer configured, and billing it, is worse than failing the batch.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    DestinationRunContext,
    DestinationWriter,
)

# A writer class is the usual factory: calling it with the run context builds the writer.
DestinationWriterFactory = Callable[[DestinationRunContext], Any]

_writer_factories: dict[str, DestinationWriterFactory] = {}


class UnsupportedDestinationError(Exception):
    def __init__(self, destination_type: str) -> None:
        super().__init__(
            f"No writer registered for destination type '{destination_type}'. "
            f"Registered types: {sorted(_writer_factories) or 'none'}"
        )
        self.destination_type = destination_type


def register_destination_writer(destination_type: str, factory: DestinationWriterFactory) -> None:
    _writer_factories[destination_type] = factory


def resolve_destination_writer(ctx: DestinationRunContext) -> DestinationWriter:
    try:
        factory = _writer_factories[ctx.destination_type]
    except KeyError:
        raise UnsupportedDestinationError(ctx.destination_type)
    return factory(ctx)


def snapshot_registered_writers() -> dict[str, DestinationWriterFactory]:
    """A copy of the registry, for a caller that will put it back.

    The registry is process-global, so a test that registers a fake writer leaks it into every
    test that runs after it. Pair with `restore_registered_writers`.
    """
    return dict(_writer_factories)


def restore_registered_writers(snapshot: dict[str, DestinationWriterFactory]) -> None:
    _writer_factories.clear()
    _writer_factories.update(snapshot)


def supported_destination_types() -> frozenset[str]:
    return frozenset(_writer_factories)


def is_destination_supported(destination_type: str) -> bool:
    return destination_type in _writer_factories
