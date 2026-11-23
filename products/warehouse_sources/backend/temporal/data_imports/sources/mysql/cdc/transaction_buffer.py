"""Holds one binlog transaction's changes until its commit gives them a position."""

from __future__ import annotations

import json
import base64
import decimal
import datetime as dt
import dataclasses
from collections.abc import Iterator, Mapping
from typing import Any

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCTransactionTooLargeError
from products.warehouse_sources.backend.temporal.data_imports.cdc.spill import (
    CDCSpillBudgetExhaustedError,
    SpillFile,
    worker_spill_budget,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import ChangeEvent

SPILL_CHUNK_EVENTS = 50_000
MAX_TRANSACTION_EVENTS = 50_000_000
MAX_SPILL_BYTES = 64 * 1024**3


def _encode(value: Any) -> Any:
    """A binlog value as JSON. The types JSON lacks are tagged with a one-key object."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, decimal.Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, dt.datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, dt.date):
        return {"$date": value.isoformat()}
    if isinstance(value, dt.time):
        return {"$time": value.isoformat()}
    if isinstance(value, dt.timedelta):
        return {"$timedelta": value // dt.timedelta(microseconds=1)}
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode()}
    raise TypeError(f"Can't spill a binlog value of type {type(value).__name__}")


_DECODERS = {
    "$decimal": decimal.Decimal,
    "$datetime": dt.datetime.fromisoformat,
    "$date": dt.date.fromisoformat,
    "$time": dt.time.fromisoformat,
    "$timedelta": lambda micros: dt.timedelta(microseconds=micros),
    "$bytes": base64.b64decode,
}


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        [(tag, raw)] = value.items()
        return _DECODERS[tag](raw)
    return value


def _encode_row(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return None if row is None else {name: _encode(value) for name, value in row.items()}


def _decode_row(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return None if row is None else {name: _decode(value) for name, value in row.items()}


class TransactionBuffer:
    """Changes of the open transaction: the latest chunk in memory, earlier ones on disk as JSON lines."""

    def __init__(self) -> None:
        self._events: list[ChangeEvent] = []
        self._count = 0
        self._spill: SpillFile | None = None
        # Arrow types can't be written as JSON, and every change of one table map shares one mapping.
        self._spill_types: list[Mapping[str, pa.DataType] | None] = []

    def __len__(self) -> int:
        return self._count

    def add(self, event: ChangeEvent) -> None:
        self._count += 1
        if self._count > MAX_TRANSACTION_EVENTS:
            self.discard()
            raise CDCTransactionTooLargeError(
                f"Transaction buffered more than {MAX_TRANSACTION_EVENTS} changes before COMMIT"
            )
        self._events.append(event)
        if len(self._events) >= SPILL_CHUNK_EVENTS:
            self._spill_chunk()

    def commit(self, position: str, committed_at: dt.datetime) -> Iterator[ChangeEvent]:
        """Yield the transaction's changes in binlog order, each at the commit position and time, and empty
        the buffer."""
        spill, types, tail = self._spill, self._spill_types, self._events
        self._spill, self._spill_types, self._events, self._count = None, [], [], 0
        try:
            if spill is not None:
                spill.file.seek(0)
                for line in spill.file:
                    operation, table_name, columns, type_index, previous_values = json.loads(line)
                    yield ChangeEvent(
                        operation=operation,
                        table_name=table_name,
                        position_serialized=position,
                        timestamp=committed_at,
                        columns=_decode_row(columns) or {},
                        column_types=types[type_index],
                        previous_values=_decode_row(previous_values),
                    )
            for event in tail:
                yield dataclasses.replace(event, position_serialized=position, timestamp=committed_at)
        finally:
            if spill is not None:
                spill.close()

    def discard(self) -> None:
        if self._spill is not None:
            self._spill.close()
        self._spill, self._spill_types, self._events, self._count = None, [], [], 0

    def _spill_chunk(self) -> None:
        budget = worker_spill_budget
        cap = min(MAX_SPILL_BYTES, budget.limit)
        if self._spill is None:
            self._spill = SpillFile(budget)
        type_index = {id(types): index for index, types in enumerate(self._spill_types)}
        for event in self._events:
            key = id(event.column_types)
            if key not in type_index:
                type_index[key] = len(self._spill_types)
                self._spill_types.append(event.column_types)
            line = (
                json.dumps(
                    [
                        event.operation,
                        event.table_name,
                        _encode_row(event.columns),
                        type_index[key],
                        _encode_row(event.previous_values),
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
                + b"\n"
            )
            if self._spill.bytes + len(line) > cap:
                self.discard()
                raise CDCTransactionTooLargeError(f"Transaction spilled more than {cap} bytes before COMMIT")
            if not self._spill.write(line):
                self.discard()
                raise CDCSpillBudgetExhaustedError(
                    f"Worker spill budget of {budget.limit} bytes is in use by other transactions"
                )
        self._events = []
