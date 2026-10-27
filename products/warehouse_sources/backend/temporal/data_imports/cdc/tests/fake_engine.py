"""An in-memory CDC engine with no Postgres in it.

It implements the adapter and reader interfaces over the scripted database of the conformance kit.
Its positions are zero-padded transaction numbers, so shared code that assumed an LSN fails here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING, Any, Literal

from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import CDCSourceAdapter
from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCErrorInfo
from products.warehouse_sources.backend.temporal.data_imports.cdc.tests.conformance_kit import (
    RowChange,
    SourceDatabase,
    Transaction,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import CDCConfig, CDCStreamReader, ChangeEvent

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

_STREAM_NAME = "fake_stream"
_CAPTURE_SET_NAME = "fake_capture_set"
# Raised by the adapter methods that only setup, the sweeper and repair call, so a test that starts
# to reach one fails instead of trusting behavior nothing checks.
_NOT_EXERCISED = "The conformance suite does not exercise this adapter method"


class FakeStreamLostError(Exception):
    pass


def _position(transaction_number: int) -> str:
    return f"{transaction_number:012d}"


class FakeCDCStreamReader:
    def __init__(self, db: SourceDatabase) -> None:
        self._db = db
        self._truncated: list[str] = []
        self._key_change_columns: dict[str, frozenset[str]] = {}
        self._last_commit_position: str | None = None
        self.last_rows_consumed = 0

    def connect(self) -> None:
        return None

    def read_changes(
        self, upto_nchanges: int | None = None, on_row: Callable[[], None] | None = None
    ) -> Iterator[ChangeEvent]:
        self.last_rows_consumed = 0
        if self._db.stream_lost:
            raise FakeStreamLostError("the change stream no longer exists")
        for transaction in self._db.pending():
            self._last_commit_position = _position(transaction.number)
            truncated: list[str] = []
            for change in transaction.changes:
                self.last_rows_consumed += 1
                if on_row is not None:
                    on_row()
                if change.op == "T":
                    truncated.append(change.table)
                else:
                    yield self._event(change, transaction)
            # A truncate becomes visible only after the caller consumed the changes before it.
            self._truncated.extend(truncated)
            # A read never splits a transaction, so the limit is checked between transactions.
            if upto_nchanges is not None and self.last_rows_consumed >= upto_nchanges:
                return

    def _event(self, change: RowChange, transaction: Transaction) -> ChangeEvent:
        assert change.op != "T"
        table = self._db.tables[change.table]
        previous_values: dict[str, object] | None = None
        columns = change.row
        if change.op == "D":
            # Only the key, as an engine that does not log full row images sends a delete.
            columns = {column: change.row[column] for column in table.primary_key}
        elif change.op == "U" and change.old_row is not None:
            watched = self._key_change_columns.get(change.table, frozenset())
            changed = {name: change.old_row[name] for name in watched if change.old_row[name] != change.row[name]}
            previous_values = changed or None
        return ChangeEvent(
            operation=change.op,
            table_name=change.table,
            position_serialized=_position(transaction.number),
            timestamp=transaction.committed_at,
            columns=dict(columns),
            previous_values=previous_values,
        )

    def confirm_position(self, position: str) -> None:
        self._db.confirm(int(position))

    def current_position(self) -> str | None:
        return _position(self._db.head)

    def get_primary_key_columns(self, schema_name: str, table_names: list[str]) -> dict[str, list[str]]:
        return self._db.primary_keys(schema_name, table_names)

    def get_enforced_unique_keys(self, schema_name: str, table_names: list[str]) -> dict[str, list[frozenset[str]]]:
        return self._db.unique_keys(schema_name, table_names)

    def set_key_change_columns(self, columns_by_table: Mapping[str, Iterable[str]]) -> None:
        self._key_change_columns = {table: frozenset(columns) for table, columns in columns_by_table.items()}

    def get_decoder_key_columns(self, table_name: str) -> list[str]:
        table = self._db.tables.get(table_name)
        return list(table.primary_key) if table is not None else []

    @property
    def truncated_tables(self) -> list[str]:
        return list(self._truncated)

    def clear_truncated_tables(self) -> None:
        self._truncated.clear()

    @property
    def last_commit_end_lsn(self) -> str | None:
        return self._last_commit_position

    def close(self) -> None:
        return None


class FakeCDCAdapter:
    def __init__(self, db: SourceDatabase) -> None:
        self._db = db

    def create_reader(self, source: ExternalDataSource) -> CDCStreamReader:
        return FakeCDCStreamReader(self._db)

    def position_to_seq(self, position_serialized: str) -> int:
        return int(position_serialized)

    @contextmanager
    def management_connection(self, source: ExternalDataSource, connect_timeout: int = 15) -> Iterator[Any]:
        yield self._db

    def validate_prerequisites(
        self,
        source: ExternalDataSource,
        management_mode: Literal["posthog", "self_managed"],
        tables: list[str],
        schema: str,
        slot_name: str | None,
        publication_name: str | None,
    ) -> list[str]:
        raise NotImplementedError(_NOT_EXERCISED)

    def drop_resources(self, conn: Any, slot_name: str, pub_name: str) -> None:
        raise NotImplementedError(_NOT_EXERCISED)

    def slot_exists(self, conn: Any, slot_name: str) -> bool:
        raise NotImplementedError(_NOT_EXERCISED)

    def get_lag_bytes(self, conn: Any, slot_name: str) -> int | None:
        raise NotImplementedError(_NOT_EXERCISED)

    def get_retention_cap_mb(self, conn: Any) -> int | None:
        raise NotImplementedError(_NOT_EXERCISED)

    def is_slot_invalidation_error(self, exc: BaseException) -> bool:
        return isinstance(exc, FakeStreamLostError)

    def is_connection_error(self, exc: BaseException) -> bool:
        raise NotImplementedError(_NOT_EXERCISED)

    def customer_fixable_error_message(self, exc: BaseException) -> str | None:
        raise NotImplementedError(_NOT_EXERCISED)

    def classify_error(self, exc: BaseException) -> CDCErrorInfo | None:
        return None

    def recreate_slot(self, source: ExternalDataSource, tables: list[str]) -> dict[str, Any]:
        return {"cdc_consistent_point": _position(self._db.recreate_stream())}

    def parse_cdc_config(self, source: ExternalDataSource) -> CDCConfig:
        return CDCConfig(
            enabled=True,
            slot_name=_STREAM_NAME,
            publication_name=_CAPTURE_SET_NAME,
            management_mode="posthog",
            lag_warning_threshold_mb=512,
            lag_critical_threshold_mb=2048,
            auto_drop_slot=True,
        )

    def setup_resources(self, source: ExternalDataSource, payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        raise NotImplementedError(_NOT_EXERCISED)

    def cleanup_resources(self, source: ExternalDataSource) -> None:
        raise NotImplementedError(_NOT_EXERCISED)

    def get_status(self, source: ExternalDataSource) -> dict[str, Any]:
        raise NotImplementedError(_NOT_EXERCISED)

    def add_table(self, source: ExternalDataSource, schema: str, table: str) -> None:
        raise NotImplementedError(_NOT_EXERCISED)

    def remove_table(self, source: ExternalDataSource, schema: str, table: str) -> None:
        raise NotImplementedError(_NOT_EXERCISED)


class FakeEngine:
    source_type = "FakeEngine"

    def __init__(self, db: SourceDatabase) -> None:
        # Typed as the interface, so that the type checker proves the fake still implements it.
        self.adapter: CDCSourceAdapter[CDCConfig] = FakeCDCAdapter(db)

    def job_inputs(self) -> dict[str, Any]:
        return {"schema": "public"}

    def installed(self) -> AbstractContextManager[None]:
        return nullcontext()
