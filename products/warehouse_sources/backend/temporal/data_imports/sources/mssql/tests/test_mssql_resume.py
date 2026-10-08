import re
import uuid
import datetime
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import Table
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mssql import MSSQLSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql import (
    MSSQLColumn,
    MSSQLImplementation,
    MSSQLResumeState,
    MSSQLUniqueIndex,
    resolve_mssql_keyset,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mssql.source import MSSQLSource
from products.warehouse_sources.backend.types import ExternalDataSchemaSyncType, IncrementalFieldType

_MSSQL_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql"
_CHUNK_ROWS = 3


def _make_config() -> MSSQLSourceConfig:
    return MSSQLSourceConfig.from_dict(
        {"host": "localhost", "port": 1433, "database": "d", "user": "u", "password": "p", "schema": "dbo"}
    )


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "orders",
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class _FakeRedis:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def exists(self, key: str) -> int:
        return int(key in self._store)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


class _MemoryResumeManager(ResumableSourceManager[MSSQLResumeState]):
    def __init__(self, store: dict[str, str]) -> None:
        super().__init__(_make_inputs(), MSSQLResumeState)
        self.store = store

    @contextmanager
    def _get_redis(self) -> Iterator[_FakeRedis]:
        yield _FakeRedis(self.store)


def _comparable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


class _FakeCursor:
    def __init__(self, server: "_FakeSQLServer") -> None:
        self._server = server
        self._pending: list[tuple[Any, ...]] = []
        self.description: list[tuple[str]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, query: str, args: dict[str, Any] | None = None) -> None:
        args = args or {}
        self._server.queries.append((query, args))
        columns = self._server.columns
        order_columns = [columns.index(name) for name in re.findall(r"\[(\w+)\] ASC", query.partition("ORDER BY")[2])]

        def order(row: tuple[Any, ...]) -> tuple[Any, ...]:
            return tuple(_comparable(row[index]) for index in order_columns)

        rows = sorted(self._server.rows, key=order)
        if "keyset_0" in args:
            after = tuple(_comparable(args[f"keyset_{index}"]) for index in range(len(order_columns)))
            rows = [row for row in rows if order(row) > after]
        if "incremental_value" in args:
            match = re.search(r"\[(\w+)\] (>=|>) %\(incremental_value\)s", query)
            assert match is not None
            position, floor = columns.index(match.group(1)), _comparable(args["incremental_value"])
            inclusive = match.group(2) == ">="
            rows = [
                row
                for row in rows
                if row[position] is not None
                and (_comparable(row[position]) > floor or (inclusive and _comparable(row[position]) == floor))
            ]
        top = re.search(r"TOP \((\d+)\)", query)
        if top is not None:
            rows = rows[: int(top.group(1))]
        self._pending = rows
        self.description = [(name,) for name in columns]

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        page, self._pending = self._pending[:size], self._pending[size:]
        return page


class _FakeSQLServer:
    def __init__(self, columns: list[str], rows: list[tuple[Any, ...]]) -> None:
        self.columns = columns
        self.rows = rows
        self.queries: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> "_FakeSQLServer":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def autocommit(self, status: bool) -> None:
        return None

    def cursor(self, **kwargs: Any) -> _FakeCursor:
        return _FakeCursor(self)


def _index(columns: list[tuple[str, str, bool]], *, clustered: bool = False, primary: bool = False) -> MSSQLUniqueIndex:
    return MSSQLUniqueIndex(
        name="ix_" + "_".join(name for name, _, _ in columns),
        is_clustered=clustered,
        is_primary_key=primary,
        columns=columns,
    )


_UUIDS = [uuid.UUID(int=(index * 7919 + 13) << 64 | index) for index in range(10)]
_DAYS = [datetime.date(2001, 1, 1) + datetime.timedelta(days=index * 40) for index in range(10)]

# name -> (columns as (name, data type), primary key, unique indexes, rows)
_TABLES: dict[str, tuple[list[tuple[str, str]], list[str] | None, list[MSSQLUniqueIndex], list[tuple[Any, ...]]]] = {
    "bigint_key": (
        [("id", "bigint"), ("note", "nvarchar")],
        ["id"],
        [_index([("id", "bigint", False)], clustered=True, primary=True)],
        [(index * 3_000_000_000 - 9, f"note {index}" if index % 3 else None) for index in range(10)],
    ),
    "uuid_key": (
        [("id", "uniqueidentifier"), ("amount", "int")],
        ["id"],
        [_index([("id", "uniqueidentifier", False)], primary=True)],
        [(key, index) for index, key in enumerate(reversed(_UUIDS))],
    ),
    "date_key": (
        [("day", "date"), ("amount", "int")],
        ["day"],
        [_index([("day", "date", False)], clustered=True, primary=True)],
        [(day, index) for index, day in enumerate(_DAYS)],
    ),
    "composite_key": (
        [("tenant", "int"), ("id", "uniqueidentifier"), ("amount", "int")],
        ["tenant", "id"],
        [_index([("tenant", "int", False), ("id", "uniqueidentifier", False)], clustered=True, primary=True)],
        [(index % 3, key, index) for index, key in enumerate(_UUIDS)],
    ),
    "unique_index_without_primary_key": (
        [("code", "int"), ("amount", "int")],
        None,
        [_index([("code", "int", False)])],
        [(100 - index * 7, None if index % 4 == 0 else index) for index in range(10)],
    ),
    "nullable_unique_index": (
        [("code", "int"), ("amount", "int")],
        None,
        [_index([("code", "int", True)])],
        [(None if index == 4 else index, index) for index in range(10)],
    ),
    "no_key": (
        [("id", "int"), ("amount", "int")],
        None,
        [],
        [(None if index % 4 == 0 else index, index) for index in range(10)],
    ),
    "text_key": (
        [("id", "varchar"), ("amount", "int")],
        ["id"],
        [_index([("id", "varchar", False)], clustered=True, primary=True)],
        [(f"key-{index}", index) for index in range(10)],
    ),
}

_KEYSET_TABLES = ["bigint_key", "uuid_key", "date_key", "composite_key", "unique_index_without_primary_key"]
_SINGLE_QUERY_TABLES = ["nullable_unique_index", "no_key", "text_key"]

_INCREMENTAL_COLUMNS = [("id", "int"), ("updated_at", "datetime2")]
_INCREMENTAL_START = datetime.datetime(2020, 1, 1)
# Two rows share each value, so a batch of three rows always ends between rows of one value.
_INCREMENTAL_ROWS = [
    (index, _INCREMENTAL_START + datetime.timedelta(seconds=index // 2, microseconds=250_000)) for index in range(10)
]
_INCREMENTAL_INPUTS: dict[str, Any] = {
    "should_use_incremental_field": True,
    "incremental_field": "updated_at",
    "incremental_field_type": IncrementalFieldType.DateTime,
    "db_incremental_field_last_value": _INCREMENTAL_START,
    "sync_type": ExternalDataSchemaSyncType.INCREMENTAL,
}


@pytest.fixture
def serve(mocker):
    def _serve(
        columns: list[tuple[str, str]],
        primary_keys: list[str] | None,
        unique_indexes: list[MSSQLUniqueIndex],
        rows: list[tuple[Any, ...]],
    ) -> _FakeSQLServer:
        table = Table(
            name="orders",
            parents=("dbo",),
            columns=[MSSQLColumn(name=name, data_type=data_type, nullable=True) for name, data_type in columns],
        )
        mocker.patch.object(MSSQLImplementation, "get_table_metadata", return_value=table)
        mocker.patch.object(MSSQLImplementation, "get_primary_keys_for_table", return_value=primary_keys)
        mocker.patch.object(MSSQLImplementation, "get_unique_indexes_for_table", return_value=unique_indexes)
        mocker.patch.object(MSSQLImplementation, "get_rows_to_sync", return_value=0)
        mocker.patch.object(MSSQLImplementation, "get_chunk_size", return_value=_CHUNK_ROWS)
        mocker.patch.object(MSSQLImplementation, "get_partition_settings", return_value=None)
        server = _FakeSQLServer([name for name, _ in columns], rows)
        mocker.patch(f"{_MSSQL_MODULE}.pymssql.connect", return_value=server)
        return server

    return _serve


def _build(store: dict[str, str], **input_overrides: Any) -> tuple[SourceResponse, _MemoryResumeManager]:
    manager = _MemoryResumeManager(store)
    source = MSSQLImplementation().build_pipeline(
        _make_config(), _make_inputs(**input_overrides), resumable_source_manager=manager
    )
    return source, manager


def _read(
    store: dict[str, str], *, stop_after: int | None = None, write_last: bool = True, **input_overrides: Any
) -> list[dict[str, Any]]:
    # Mirrors the pipeline: it writes each batch it receives, then commits the staged checkpoint.
    source, manager = _build(store, **input_overrides)
    written: list[dict[str, Any]] = []
    items = source.items()
    for index, table in enumerate(items, start=1):  # type: ignore[arg-type]
        if index == stop_after and not write_last:
            break
        written.extend(table.to_pylist())
        manager.confirm()
        manager.commit()
        if index == stop_after:
            break
    items.close()  # type: ignore[union-attr]
    return written


class TestKeysetFullRefresh:
    @pytest.mark.parametrize("write_last", [True, False])
    @pytest.mark.parametrize("stop_after", [1, 2, 3])
    @pytest.mark.parametrize("table", _KEYSET_TABLES)
    def test_interrupted_read_resumes_to_the_rows_of_an_uninterrupted_read(self, serve, table, stop_after, write_last):
        server = serve(*_TABLES[table])
        uninterrupted = _read({})
        assert len(uninterrupted) == len(server.rows)

        store: dict[str, str] = {}
        first = _read(store, stop_after=stop_after, write_last=write_last)
        resumed = _read(store)

        assert first + resumed == uninterrupted
        assert store == {}

    @pytest.mark.parametrize("table", _SINGLE_QUERY_TABLES)
    def test_table_without_a_usable_key_reads_on_the_single_query(self, serve, table):
        server = serve(*_TABLES[table])
        source, _ = _build({})
        store: dict[str, str] = {}

        rows = _read(store)

        assert source.supports_resume is False
        assert len(rows) == len(server.rows)
        assert store == {}
        assert all("TOP" not in query and "ORDER BY" not in query for query, _ in server.queries)

    def test_checkpoint_for_other_key_columns_restarts_the_read(self, serve):
        server = serve(*_TABLES["bigint_key"])
        store: dict[str, str] = {}
        manager = _MemoryResumeManager(store)
        manager.save_state(MSSQLResumeState(key_columns=["legacy_id"], last_key=[10**12]))
        manager.confirm()
        manager.commit()

        source, manager = _build(store)

        # The pipeline checks the checkpoint after build_pipeline returns. Clearing an incompatible
        # checkpoint here makes it replace the partial table instead of treating a fresh read as a resume.
        assert manager.can_resume() is False
        assert sum(table.num_rows for table in source.items()) == len(server.rows)  # type: ignore[union-attr]

    def test_reset_ignores_the_checkpoint(self, serve):
        server = serve(*_TABLES["bigint_key"])
        store: dict[str, str] = {}
        _read(store, stop_after=2)
        manager = _MemoryResumeManager(store)

        source = MSSQLSource().source_for_pipeline(_make_config(), manager, _make_inputs(reset_pipeline=True))

        assert sum(table.num_rows for table in source.items()) == len(server.rows)  # type: ignore[union-attr]


class TestResolveKeyset:
    @pytest.mark.parametrize(
        "indexes,readable,incremental,expected_columns,expected_reason",
        [
            ([_index([("id", "int", False)], primary=True)], {"id"}, False, ["id"], None),
            ([_index([("id", "int", False)], primary=True)], {"id"}, True, None, "incremental_sync"),
            ([], {"id"}, False, None, "no_unique_index"),
            ([_index([("id", "int", True)])], {"id"}, False, None, "nullable_key"),
            ([_index([("id", "nvarchar", False)], primary=True)], {"id"}, False, None, "non_orderable_type:nvarchar"),
            ([_index([("id", "datetime2", False)], primary=True)], {"id"}, False, None, "non_orderable_type:datetime2"),
            ([_index([("code", "int", False)])], {"id"}, False, None, "key_not_projected"),
            (
                [
                    _index([("id", "uniqueidentifier", False)], primary=True),
                    _index([("seq", "bigint", False)], clustered=True),
                ],
                {"id", "seq"},
                False,
                ["seq"],
                None,
            ),
            (
                [_index([("a", "int", False), ("b", "int", False)]), _index([("id", "int", False)], primary=True)],
                {"a", "b", "id"},
                False,
                ["id"],
                None,
            ),
            (
                [_index([("id", "varchar", False)], clustered=True, primary=True), _index([("code", "int", False)])],
                {"id", "code"},
                False,
                ["code"],
                None,
            ),
            (
                [_index([("a", "int", False), ("b", "date", True)], primary=True)],
                {"a", "b"},
                False,
                None,
                "nullable_key",
            ),
        ],
    )
    def test_picks_the_key_or_names_the_reason(self, indexes, readable, incremental, expected_columns, expected_reason):
        keyset = resolve_mssql_keyset(
            unique_indexes=indexes, readable_columns=readable, should_use_incremental_field=incremental
        )
        assert (keyset.columns, keyset.reason) == (expected_columns, expected_reason)


class TestIncrementalResume:
    @pytest.mark.parametrize("write_last", [True, False])
    @pytest.mark.parametrize("stop_after", [1, 2, 3])
    def test_interrupted_read_resumes_from_the_last_written_value(self, serve, stop_after, write_last):
        server = serve(_INCREMENTAL_COLUMNS, ["id"], [], _INCREMENTAL_ROWS)
        uninterrupted = _read({}, **_INCREMENTAL_INPUTS)

        store: dict[str, str] = {}
        first = _read(store, stop_after=stop_after, write_last=write_last, **_INCREMENTAL_INPUTS)
        server.queries.clear()
        resumed = _read(store, **_INCREMENTAL_INPUTS)

        merged = {row["id"]: row for row in first + resumed}
        assert sorted(merged.values(), key=lambda row: row["id"]) == sorted(uninterrupted, key=lambda row: row["id"])
        assert store == {}
        # Rows at the checkpoint value are read again. Rows below it are not.
        written_batches = stop_after if write_last else stop_after - 1
        if written_batches:
            checkpoint = first[-1]["updated_at"]
            assert server.queries[-1][1]["incremental_value"] == checkpoint
            assert min(row["updated_at"] for row in resumed) == checkpoint
