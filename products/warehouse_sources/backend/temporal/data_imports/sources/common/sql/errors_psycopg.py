"""psycopg error translation shared by the Postgres and Redshift sources.

Separate from `projection.py` so the psycopg import stays off the path of the sources that don't
speak the Postgres wire protocol.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, Callable, Iterable
from typing import Any, cast

from psycopg.errors import UndefinedColumn

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.projection import (
    MISSING_PROJECTED_COLUMN_MESSAGE,
    ProjectedColumnMissingError,
)


def reader_without_dropped_columns(
    items: Callable[[], Iterable[Any] | AsyncIterable[Any]],
) -> Callable[[], Iterable[Any]]:
    """Wrap a source reader so a column dropped mid-read does not disable the schema.

    Both sources word SQLSTATE 42703 as "column ... does not exist", which their non-retryable
    rules match on to catch a dropped relation. The stale column selection is dropped against the
    catalog at the start of every run, so a column that reaches the reader vanished mid-run and
    the next run recovers on its own. Re-raise clear of that substring so it stays retryable.

    Both readers are synchronous generators; the async half of the `items` signature is there for
    the sources that stream from an API.
    """

    def read() -> Iterable[Any]:
        try:
            yield from cast(Iterable[Any], items())
        except UndefinedColumn as e:
            raise ProjectedColumnMissingError(MISSING_PROJECTED_COLUMN_MESSAGE) from e

    return read
