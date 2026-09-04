"""Batch accumulation shared by the S3-backed source managers."""

from __future__ import annotations

from typing import Generic, TypeVar

import pyarrow as pa

DEFAULT_BATCH_ROW_LIMIT = 5000
DEFAULT_BATCH_BYTE_LIMIT = 200 * 1024 * 1024

T = TypeVar("T")


class TableBatcher(Generic[T]):
    """Accumulate tables until a row or byte limit, carrying each table's source item alongside.

    Accumulation only: when a file may be deleted differs per manager — the change buffer deletes on
    proof of consumption, the webhook producer deletes once its batch is yielded — and that contract
    stays with the caller.
    """

    def __init__(self, *, row_limit: int = DEFAULT_BATCH_ROW_LIMIT, byte_limit: int = DEFAULT_BATCH_BYTE_LIMIT) -> None:
        self._row_limit = row_limit
        self._byte_limit = byte_limit
        self.tables: list[pa.Table] = []
        self.items: list[T] = []
        self._rows = 0
        self._bytes = 0

    def add(self, table: pa.Table, item: T | None = None) -> bool:
        """Take one table, reporting whether the batch has reached a limit and should be yielded."""
        self.tables.append(table)
        if item is not None:
            self.items.append(item)
        self._rows += table.num_rows
        self._bytes += table.nbytes
        return self._rows >= self._row_limit or self._bytes >= self._byte_limit

    def reset(self) -> None:
        self.tables = []
        self.items = []
        self._rows = 0
        self._bytes = 0

    def __bool__(self) -> bool:
        return bool(self.tables)
