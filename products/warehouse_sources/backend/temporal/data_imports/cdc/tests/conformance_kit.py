"""Harness for the CDC conformance suite.

A scripted source database records committed transactions. An engine renders them in its own change
stream format, and the kit runs the shared capture and consume code over that stream. Change events
therefore always come from an engine's reader, never from a fixture typed by hand.
"""

from __future__ import annotations

import io
import copy
import uuid
import asyncio
import hashlib
import datetime as dt
from collections import defaultdict
from collections.abc import AsyncIterator, Callable, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, ExitStack, asynccontextmanager, contextmanager
from types import SimpleNamespace, TracebackType
from typing import Any, Literal, Protocol, Self, cast

from unittest.mock import MagicMock, patch

import pyarrow as pa
import structlog
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.models.external_data_schema import CDC_SNAPSHOT_LANE_KEY, ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.activities import CDCExtractActivity, CDCExtractInput
from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import CDCSourceAdapter
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    CDC_OP_COLUMN,
    CDC_SEQ_COLUMN,
    CDC_TIMESTAMP_COLUMN,
    DELETED_COLUMN,
    TOAST_OMITTED_COLUMN,
    companion_resource_name,
    enrich_delete_rows,
    enrich_toast_omitted_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import get_buffer_prefix
from products.warehouse_sources.backend.temporal.data_imports.cdc.lane_position import LanePosition, content_columns
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import resolve_batch
from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import (
    COMPANION_WRITE_MODE,
    CONSOLIDATED_WRITE_MODE,
    CDCSourceManager,
    ListingProof,
    build_output_lanes,
    consolidated_resource_name,
    purge_buffer_before_handover,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import CDCConfig
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.common import strip_s3_protocol
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs

_CDC = "products.warehouse_sources.backend.temporal.data_imports.cdc"
_FACADE = "products.data_warehouse.backend.facade"
_TEAM_ID = 1
_FIRST_COMMIT_AT = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

Key = tuple[Any, ...]
Row = dict[str, Any]
# One history row as the suite compares it: the operation, the source columns, and the commit time.
HistoryEntry = tuple[str, Row, dt.datetime]


class SimulatedCrash(Exception):
    pass


@frozen
class TableDef:
    # Qualified `schema.table`, as engines name a table in their change stream.
    name: str
    columns: dict[str, type]
    primary_key: tuple[str, ...]

    def key_of(self, row: Row) -> Key:
        return tuple(row[column] for column in self.primary_key)


@frozen
class Statement:
    op: Literal["I", "U", "D", "T"]
    table: TableDef
    key: Row
    values: Row


def insert(table: TableDef, **row: Any) -> Statement:
    return Statement(op="I", table=table, key={}, values=row)


def update(table: TableDef, key: Row, **changes: Any) -> Statement:
    return Statement(op="U", table=table, key=key, values=changes)


def delete(table: TableDef, **key: Any) -> Statement:
    return Statement(op="D", table=table, key=key, values={})


def truncate(table: TableDef) -> Statement:
    return Statement(op="T", table=table, key={}, values={})


@frozen
class RowChange:
    op: Literal["I", "U", "D", "T"]
    table: str
    # The row after an insert or update, and the removed row of a delete.
    row: Row
    old_row: Row | None


@frozen
class Transaction:
    # 1-based commit order. Engines derive their own position format from it.
    number: int
    committed_at: dt.datetime
    changes: tuple[RowChange, ...]


class SourceDatabase:
    """The source of truth for a scenario, with the change stream state every engine shares."""

    def __init__(self, tables: Sequence[TableDef]) -> None:
        self.tables = {table.name: table for table in tables}
        self.log: list[Transaction] = []
        # The stream holds every transaction above this number.
        self.confirmed = 0
        self.stream_lost = False
        self.stream_recreations = 0
        self._rows: dict[str, dict[Key, Row]] = {table.name: {} for table in tables}
        self._failing_confirms = 0

    @property
    def head(self) -> int:
        return len(self.log)

    def rows(self, table: TableDef) -> dict[Key, Row]:
        return dict(self._rows[table.name])

    def commit(self, *statements: Statement) -> Transaction:
        changes: list[RowChange] = []
        for statement in statements:
            table, rows = statement.table, self._rows[statement.table.name]
            if statement.op == "I":
                rows[table.key_of(statement.values)] = dict(statement.values)
                changes.append(RowChange(op="I", table=table.name, row=dict(statement.values), old_row=None))
            elif statement.op == "U":
                old = rows.pop(table.key_of(statement.key))
                new = {**old, **statement.values}
                rows[table.key_of(new)] = new
                changes.append(RowChange(op="U", table=table.name, row=new, old_row=old))
            elif statement.op == "D":
                old = rows.pop(table.key_of(statement.key))
                changes.append(RowChange(op="D", table=table.name, row=old, old_row=old))
            else:
                rows.clear()
                changes.append(RowChange(op="T", table=table.name, row={}, old_row=None))
        number = self.head + 1
        transaction = Transaction(
            number=number, committed_at=_FIRST_COMMIT_AT + dt.timedelta(seconds=number), changes=tuple(changes)
        )
        self.log.append(transaction)
        return transaction

    def primary_keys(self, namespace: str, relations: list[str]) -> dict[str, list[str]]:
        return {name: list(self.tables[f"{namespace}.{name}"].primary_key) for name in relations}

    def unique_keys(self, namespace: str, relations: list[str]) -> dict[str, list[frozenset[str]]]:
        return {name: [frozenset(self.tables[f"{namespace}.{name}"].primary_key)] for name in relations}

    def pending(self) -> list[Transaction]:
        return [transaction for transaction in self.log if transaction.number > self.confirmed]

    def confirm(self, number: int) -> None:
        if self._failing_confirms:
            self._failing_confirms -= 1
            raise SimulatedCrash("the stream position could not be confirmed")
        self.confirmed = max(self.confirmed, number)

    def fail_next_confirm(self) -> None:
        self._failing_confirms += 1

    def lose_stream(self) -> None:
        self.stream_lost = True

    def recreate_stream(self) -> int:
        """A new stream starts at the current end of the log, so the changes before it are gone."""
        self.stream_lost = False
        self.stream_recreations += 1
        self.confirmed = self.head
        return self.confirmed

    def expected_history(self, table: TableDef) -> list[HistoryEntry]:
        """Every row version of the table in commit order, with a key change as a delete and an insert.

        A delete carries the values of the row it removed, which the loader fills in for a delete that
        arrives with its key only.
        """
        expected: list[HistoryEntry] = []
        for transaction in self.log:
            at = transaction.committed_at
            for change in transaction.changes:
                if change.table != table.name or change.op == "T":
                    continue
                old = change.old_row
                if change.op == "U" and old is not None and table.key_of(old) != table.key_of(change.row):
                    expected += [("D", dict(old), at), ("I", dict(change.row), at)]
                else:
                    expected.append((change.op, dict(change.row), at))
        return expected


class ConformanceEngine(Protocol):
    """What an engine provides to run the suite: its adapter, and a change stream over the database."""

    source_type: str
    adapter: CDCSourceAdapter[CDCConfig]

    def job_inputs(self) -> dict[str, Any]: ...

    def installed(self) -> AbstractContextManager[None]:
        """Connects the engine's own client code to the scripted database for the length of a test."""
        ...


class _AsyncFile:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def read(self) -> bytes:
        return self._data


class MemoryObjectStore:
    """The parts of the sync and async S3 clients that the change buffer uses."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self._writes = 0
        self._failing_writes: set[int] = set()

    def fail_write(self, nth: int) -> None:
        self._failing_writes.add(self._writes + nth)

    @contextmanager
    def open(self, key: str, mode: str) -> Iterator[io.BytesIO]:
        if mode == "rb":
            if key not in self.objects:
                raise FileNotFoundError(key)
            yield io.BytesIO(self.objects[key])
            return
        self._writes += 1
        buffer = io.BytesIO()
        yield buffer
        written = buffer.getvalue()
        if self._writes in self._failing_writes:
            # The S3 client flushes what it buffered when a write fails, so a truncated object lands
            # under the final name. The writer has to remove it.
            self.objects[key] = written[: len(written) // 2]
            raise SimulatedCrash("the buffer file could not be written")
        self.objects[key] = written

    def rm(self, key: str, recursive: bool = False) -> None:
        doomed = [k for k in self.objects if k == key or (recursive and k.startswith(f"{key}/"))]
        if not doomed:
            raise FileNotFoundError(key)
        for k in doomed:
            del self.objects[k]

    def ls(self, prefix: str, detail: bool = False, refresh: bool = False) -> list[str]:
        keys = sorted(k for k in self.objects if k.startswith(f"{prefix}/"))
        if not keys:
            raise FileNotFoundError(prefix)
        return keys

    def _etag(self, key: str) -> str:
        return hashlib.md5(self.objects[key]).hexdigest()

    async def _ls(self, prefix: str, detail: bool = True, refresh: bool = False) -> list[dict[str, Any]]:
        now = dt.datetime.now(tz=dt.UTC)
        return [
            {"type": "file", "Key": key, "LastModified": now, "ETag": f'"{self._etag(key)}"'}
            # The consumer lists by URL, and the store names an object by bucket and path.
            for key in self.ls(strip_s3_protocol(prefix))
        ]

    async def open_async(self, key: str, mode: str) -> _AsyncFile:
        if key not in self.objects:
            raise FileNotFoundError(key)
        return _AsyncFile(self.objects[key])

    async def _rm(self, key: str) -> None:
        self.rm(key)

    def split_path(self, key: str) -> tuple[str, str, None]:
        bucket, _, rest = key.partition("/")
        return bucket, rest, None

    def invalidate_cache(self, key: str) -> None:
        return None

    async def get_s3(self, bucket: str) -> MemoryObjectStore:
        return self

    async def delete_object(self, *, Bucket: str, Key: str, IfMatch: str) -> None:
        key = f"{Bucket}/{Key}"
        if key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "DeleteObject")
        if IfMatch.strip('"') != self._etag(key):
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "DeleteObject")
        del self.objects[key]


def _highest_position(rows: Sequence[Row]) -> int | None:
    positions = [row[CDC_SEQ_COLUMN] for row in rows if row.get(CDC_SEQ_COLUMN) is not None]
    return max(positions) if positions else None


def lane_position(rows: Sequence[Row], key_columns: Sequence[str] | None) -> LanePosition:
    """What `read_lane_position` returns for a table that holds these rows."""
    position = _highest_position(rows)
    if position is None or not key_columns:
        return LanePosition(position=position, applied={})
    applied: defaultdict[Key, list[Row]] = defaultdict(list)
    for row in rows:
        if row.get(CDC_SEQ_COLUMN) == position:
            identity = tuple(row.get(column) for column in key_columns)
            applied[identity].append({column: row[column] for column in content_columns(list(row))})
    return LanePosition(position=position, applied=dict(applied), key_columns=tuple(key_columns))


class Warehouse:
    """Stands in for the loader and the two Delta tables of one schema.

    It applies a batch with the same shared functions the loader calls, in the same order, and keeps
    the rows in memory. The Delta writer itself is outside the conformance contract.
    """

    def __init__(self, table: TableDef) -> None:
        self._table = table
        self._keys = list(table.primary_key)
        self.merged: dict[Key, Row] = {}
        self.history: list[Row] = []

    def merge(self, batch: pa.Table) -> None:
        if not batch.num_rows:
            return
        existing = self._existing_rows()
        batch = enrich_toast_omitted_rows(batch, self._keys, existing)
        batch = enrich_delete_rows(batch, self._keys, existing)
        batch, _ = resolve_batch(batch, self._keys, cdc_write_mode=CONSOLIDATED_WRITE_MODE)
        for row in _without_toast_marker(batch).to_pylist():
            self.merged[self._table.key_of(row)] = row

    def append_history(self, batch: pa.Table) -> None:
        if not batch.num_rows:
            return
        # The loader enriches from the open version of each key. The writer that closes the older
        # versions is not modelled here, so the open version is the last one appended.
        current = {self._table.key_of(row): row for row in self.history}
        existing = self._as_table(list(current.values()))
        batch = enrich_toast_omitted_rows(batch, self._keys, existing)
        batch = enrich_delete_rows(batch, self._keys, existing)
        self.history.extend(_without_toast_marker(batch).to_pylist())

    def reseed(self, rows: dict[Key, Row]) -> None:
        self.merged = {key: {**row, DELETED_COLUMN: False} for key, row in rows.items()}
        self.history = []

    def rows(self, *, deleted: bool) -> dict[Key, Row]:
        return {
            key: {column: row.get(column) for column in self._table.columns}
            for key, row in self.merged.items()
            if bool(row.get(DELETED_COLUMN)) is deleted
        }

    def _existing_rows(self) -> pa.Table | None:
        return self._as_table(list(self.merged.values()))

    def _as_table(self, rows: list[Row]) -> pa.Table | None:
        if not rows:
            return None
        return pa.table({column: [row.get(column) for row in rows] for column in self._table.columns})


def _without_toast_marker(batch: pa.Table) -> pa.Table:
    # The loader strips the marker before the write, so no stored row carries it.
    return batch.drop_columns([TOAST_OMITTED_COLUMN]) if TOAST_OMITTED_COLUMN in batch.column_names else batch


class _LaneTableRef:
    """Stands in for `DeltaTableRef`. The resource name is all the patched position read needs."""

    def __init__(self, resource_name: str, *_: object, **__: object) -> None:
        self._resource_name = resource_name

    async def get_delta_table(self) -> str:
        return self._resource_name


async def _keep_position_stats(*_: object, **__: object) -> None:
    return None


class ConformanceKit:
    """Runs capture and consume for one source over an engine, with every store kept in memory."""

    def __init__(self, db: SourceDatabase, engine: ConformanceEngine, captured: Sequence[TableDef]) -> None:
        self.db = db
        self.store = MemoryObjectStore()
        self._engine = engine
        self._log = structlog.get_logger()
        # The rows the app database holds. Each run and each assertion gets fresh model instances
        # built from them, so only a write that reaches the database carries over.
        self._source_id = uuid.uuid4()
        self._source_job_inputs = engine.job_inputs()
        self._schema_rows: dict[str, Row] = {
            table.name: {
                "id": uuid.uuid4(),
                "initial_sync_complete": True,
                "status": None,
                "latest_error": None,
                "sync_type_config": {
                    "cdc_mode": "streaming",
                    "cdc_table_mode": "both",
                    "primary_key_columns": list(table.primary_key),
                },
            }
            for table in captured
        }
        self._warehouses = {table.name: Warehouse(table) for table in captured}
        self._proofs: dict[str, ListingProof] = {}
        # Every listing stamp of the consume run in progress. The last one is the listing it read.
        self._listings: list[tuple[dt.datetime, dict[str, str]]] = []
        # Resource name to the rows of that table, for the consume run in progress.
        self._lane_rows: dict[str, Callable[[], list[Row]]] = {}
        self._stack = ExitStack()

    def _load_source(self) -> ExternalDataSource:
        return ExternalDataSource(
            id=self._source_id,
            team_id=_TEAM_ID,
            source_type=self._engine.source_type,
            job_inputs=copy.deepcopy(self._source_job_inputs),
            # A saved row always has one, and adapters read it.
            created_at=_FIRST_COMMIT_AT,
        )

    def _load_schema(self, name: str, source: ExternalDataSource) -> ExternalDataSchema:
        stored = copy.deepcopy(self._schema_rows[name])
        return ExternalDataSchema(
            name=name,
            team_id=_TEAM_ID,
            source=source,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
            **stored,
        )

    def _schema_row(self, schema_id: uuid.UUID | str) -> Row:
        return next(row for row in self._schema_rows.values() if str(row["id"]) == str(schema_id))

    def __enter__(self) -> Self:
        kit = self

        def merge_config(
            schema_id: uuid.UUID | str,
            team_id: int,
            *,
            updates: dict[str, Any] | None = None,
            removes: Iterable[str] | None = None,
            mutate: Callable[[dict[str, Any]], None] | None = None,
            extra_model_fields: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            stored = kit._schema_row(schema_id)
            config = copy.deepcopy(stored["sync_type_config"])
            config.update(updates or {})
            for key in removes or []:
                config.pop(key, None)
            if mutate is not None:
                mutate(config)
            stored["sync_type_config"] = config
            for field, value in (extra_model_fields or {}).items():
                stored[field] = copy.deepcopy(value)
            return copy.deepcopy(config)

        def save_schema(schema: ExternalDataSchema, *_: object, update_fields: Iterable[str] | None = None) -> None:
            stored = kit._schema_row(schema.id)
            for field in update_fields if update_fields is not None else list(stored):
                if field in stored and field != "id":
                    stored[field] = copy.deepcopy(getattr(schema, field))

        def save_source(source: ExternalDataSource, *_: object, update_fields: Iterable[str] | None = None) -> None:
            if update_fields is None or "job_inputs" in update_fields:
                kit._source_job_inputs = copy.deepcopy(source.job_inputs)

        def cdc_schemas(extraction: CDCExtractActivity) -> list[ExternalDataSchema]:
            assert extraction.source is not None
            return [kit._load_schema(name, extraction.source) for name in kit._schema_rows]

        async def read_lane_position(resource_name: str, *, key_columns: list[str] | None = None) -> LanePosition:
            return lane_position(kit._lane_rows[resource_name](), key_columns)

        @asynccontextmanager
        async def async_client() -> AsyncIterator[MemoryObjectStore]:
            yield kit.store

        async def stamp_listing(_manager: CDCSourceManager, listed_at: dt.datetime, tail: dict[str, str]) -> None:
            kit._listings.append((listed_at, dict(tail)))

        source_model = MagicMock()
        source_model.objects.get.side_effect = lambda **_: kit._load_source()
        activity = MagicMock()
        activity.info.return_value = MagicMock(attempt=1)

        patches: list[AbstractContextManager[Any]] = [
            self._engine.installed(),
            patch(f"{_CDC}.activities.get_cdc_adapter", return_value=self._engine.adapter),
            patch(f"{_CDC}.activities.source_type_supports_cdc", return_value=True),
            patch(f"{_CDC}.activities.ExternalDataSource", source_model),
            patch.object(CDCExtractActivity, "_get_cdc_schemas", cdc_schemas),
            patch(f"{_CDC}.activities.update_sync_type_config_keys", merge_config),
            patch.object(ExternalDataSchema, "save", save_schema),
            patch.object(ExternalDataSource, "save", save_source),
            # The lanes read their position from the in-memory tables instead of Delta.
            patch(f"{_CDC}.source_manager.DeltaTableRef", _LaneTableRef),
            patch(f"{_CDC}.source_manager.ensure_position_stats", _keep_position_stats),
            patch(f"{_CDC}.source_manager.read_lane_position", read_lane_position),
            # Everything below is a boundary: Temporal, Celery, analytics and S3.
            patch(f"{_CDC}.activities.close_old_connections"),
            patch(f"{_CDC}.activities.activity", activity),
            patch(f"{_CDC}.activities.posthoganalytics"),
            patch(f"{_CDC}.activities.cancel_running_sync", return_value=None),
            patch(f"{_CDC}.activities.has_queued_batches", return_value=False),
            patch(f"{_CDC}.activities.clear_slot_loss_markers"),
            patch(f"{_FACADE}.api.pause_external_data_schedule"),
            patch(f"{_FACADE}.api.unpause_external_data_schedule"),
            patch(f"{_FACADE}.api.pause_cdc_extraction_schedule"),
            patch(f"{_FACADE}.tasks.schedule_external_data_failure_digest"),
            patch(f"{_CDC}.buffer.get_s3_client", return_value=self.store),
            patch(f"{_CDC}.buffer.ensure_bucket"),
            patch(f"{_CDC}.source_manager.aget_s3_client", async_client),
            patch.object(CDCSourceManager, "stamp_listing", stamp_listing),
        ]
        # A patch that fails to start must not leave the earlier ones active for later tests.
        with ExitStack() as stack:
            for entry in patches:
                stack.enter_context(entry)
            self._stack = stack.pop_all()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self._stack.close()

    def schema(self, table: TableDef) -> ExternalDataSchema:
        """The schema as the app database holds it now."""
        return self._load_schema(table.name, self._load_source())

    def capture(self, *, read_limit: int | None = None) -> None:
        """One capture run. `read_limit` shrinks the read page, so a small backlog spans several pages."""
        inputs = CDCExtractInput(team_id=_TEAM_ID, source_id=self._source_id)
        if read_limit is None:
            CDCExtractActivity(inputs).run()
            return
        with patch(f"{_CDC}.activities.CDC_MAX_CHANGES_PER_READ", read_limit):
            CDCExtractActivity(inputs).run()

    def consume(self, table: TableDef, *, fail_history_lane: bool = False) -> None:
        """One scheduled sync of the table. `fail_history_lane` leaves the history table behind the
        consolidated one, as a run does when its companion job fails."""
        schema, warehouse = self.schema(table), self._warehouses[table.name]
        self._lane_rows = {
            consolidated_resource_name(schema): lambda: list(warehouse.merged.values()),
            companion_resource_name(schema.name): lambda: warehouse.history,
        }
        inputs = SimpleNamespace(team_id=_TEAM_ID, schema_id=str(schema.id), job_id="job")

        async def drain() -> None:
            lanes, floor = await build_output_lanes(schema, MagicMock(), self._log)
            manager = CDCSourceManager(
                cast(SourceInputs, inputs), self._log, deletion_floor=floor, proof=self._proofs.get(table.name)
            )
            async for batch in manager.get_items():
                for lane in lanes:
                    rows = lane.transform(batch) if lane.transform is not None else batch
                    if lane.cdc_write_mode != COMPANION_WRITE_MODE:
                        warehouse.merge(rows)
                    elif not fail_history_lane:
                        warehouse.append_history(rows)

        self._listings.clear()
        asyncio.run(drain())
        # Only a run that completed every table proves that it consumed what it listed.
        if self._listings and not fail_history_lane:
            listed_at, tail = self._listings[-1]
            self._proofs[table.name] = ListingProof(listed_at=listed_at, tail=tail)

    def snapshot(self, table: TableDef) -> None:
        """Completes the table's pending snapshot and hands it over to streaming."""
        purge_buffer_before_handover(self.schema(table), self._log)
        self._warehouses[table.name].reseed(self.db.rows(table))
        stored = self._schema_rows[table.name]
        config = stored["sync_type_config"]
        config["cdc_mode"] = "streaming"
        config.pop("reset_pipeline", None)
        config.pop(CDC_SNAPSHOT_LANE_KEY, None)
        stored["initial_sync_complete"] = True
        self._proofs.pop(table.name, None)

    def live_rows(self, table: TableDef) -> dict[Key, Row]:
        return self._warehouses[table.name].rows(deleted=False)

    def deleted_rows(self, table: TableDef) -> dict[Key, Row]:
        return self._warehouses[table.name].rows(deleted=True)

    def history(self, table: TableDef) -> list[HistoryEntry]:
        return [
            (row[CDC_OP_COLUMN], {column: row.get(column) for column in table.columns}, row[CDC_TIMESTAMP_COLUMN])
            for row in self._warehouses[table.name].history
        ]

    def buffered_rows(self, table: TableDef) -> list[Row]:
        prefix = strip_s3_protocol(get_buffer_prefix(_TEAM_ID, str(self._schema_rows[table.name]["id"])))
        rows: list[Row] = []
        for key in sorted(k for k in self.store.objects if k.startswith(f"{prefix}/")):
            rows.extend(pq.read_table(io.BytesIO(self.store.objects[key])).to_pylist())
        return rows
