"""Holds one binlog transaction's changes until its commit gives them a position."""

from __future__ import annotations

import pickle
import datetime as dt
import dataclasses
from collections.abc import Iterator

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


class TransactionBuffer:
    """Changes of the open transaction: the latest chunk in memory, earlier chunks pickled to a spill file.

    Binlog values include datetimes, decimals, bytes and JSON documents, so chunks are pickled rather than
    written as JSON lines.
    """

    def __init__(self) -> None:
        self._events: list[ChangeEvent] = []
        self._count = 0
        self._spill: SpillFile | None = None

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
        spill, tail = self._spill, self._events
        self._spill, self._events, self._count = None, [], 0
        try:
            if spill is not None:
                spill.file.seek(0)
                while True:
                    try:
                        chunk: list[ChangeEvent] = pickle.load(spill.file)
                    except EOFError:
                        break
                    for event in chunk:
                        yield dataclasses.replace(event, position_serialized=position, timestamp=committed_at)
            for event in tail:
                yield dataclasses.replace(event, position_serialized=position, timestamp=committed_at)
        finally:
            if spill is not None:
                spill.close()

    def discard(self) -> None:
        if self._spill is not None:
            self._spill.close()
        self._spill, self._events, self._count = None, [], 0

    def _spill_chunk(self) -> None:
        budget = worker_spill_budget
        cap = min(MAX_SPILL_BYTES, budget.limit)
        if self._spill is None:
            self._spill = SpillFile(budget)
        data = pickle.dumps(self._events, protocol=pickle.HIGHEST_PROTOCOL)
        if self._spill.bytes + len(data) > cap:
            self.discard()
            raise CDCTransactionTooLargeError(f"Transaction spilled more than {cap} bytes before COMMIT")
        if not self._spill.write(data):
            self.discard()
            raise CDCSpillBudgetExhaustedError(
                f"Worker spill budget of {budget.limit} bytes is in use by other transactions"
            )
        self._events = []
