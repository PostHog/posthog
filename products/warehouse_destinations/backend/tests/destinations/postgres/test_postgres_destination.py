import json
import typing
import asyncio
import decimal
import datetime as dt
from collections.abc import AsyncIterator
from typing import Any

import pytest

import psycopg
import pyarrow as pa
from psycopg import sql

from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models import Integration
from posthog.models.integration import TLS
from posthog.test.waiting import wait_until

from products.warehouse_destinations.backend.core import table_marker
from products.warehouse_destinations.backend.core.json_type import JsonType
from products.warehouse_destinations.backend.destinations.postgres import integration
from products.warehouse_destinations.backend.destinations.postgres.destination import (
    BATCH_KEY_COLUMN,
    PostgresDestination,
    PostgresSession,
    _lock_key,
    batch_key_index_name,
    scoped_identifier,
    staging_table_name,
)
from products.warehouse_destinations.backend.destinations.postgres.errors import (
    PERMISSIONS_DETAIL,
    ColumnTypeMappingError,
    MissingPrimaryKeyError,
    PostgreSQLConnectionConfigurationError,
    PostgreSQLIncompatibleSchemaError,
    PostgreSQLIntegrationNotFoundError,
    PostgreSQLInvalidTargetError,
    PostgreSQLMissingRequiredInputsError,
    PostgreSQLUnrelatedTableError,
)
from products.warehouse_destinations.backend.facade import api
from products.warehouse_destinations.backend.facade.contracts import (
    DestinationConfigurationError,
    DestinationConnection,
    DestinationError,
    MergeSpec,
    PreparedTarget,
    TableTarget,
    TargetRef,
)
from products.warehouse_destinations.backend.facade.enums import (
    DestinationType,
    ErrorKind,
    LogicalType,
    NewColumnPolicy,
    TypePolicy,
    WriteMode,
)
from products.warehouse_destinations.backend.facade.testing import fake_config
from products.warehouse_destinations.backend.tests.destinations.postgres.conftest import ROLE_PASSWORD


@pytest.fixture(autouse=True)
def _test_server_without_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    # The test server has no TLS, and typed-in connection details cannot ask for "prefer".
    monkeypatch.setattr(integration, "inline_tls", lambda ssl_mode: TLS(ssl_mode="prefer"))


def _schema(*fields: tuple[str, pa.DataType]) -> pa.Schema:
    return pa.schema(list(fields))


ROWS_SCHEMA = _schema(("id", pa.int64()), ("name", pa.string()))


class _OtherJsonType(pa.ExtensionType):
    """A JSON extension class that is not the product's own, like the one a caller builds."""

    def __init__(self) -> None:
        super().__init__(pa.string(), "json")

    def __arrow_ext_serialize__(self) -> bytes:
        return b""

    @classmethod
    def __arrow_ext_deserialize__(cls, storage_type: pa.DataType, serialized: bytes) -> "_OtherJsonType":
        return cls()


def _rows(*rows: tuple[int, str]) -> pa.RecordBatch:
    return pa.RecordBatch.from_pylist([{"id": i, "name": n} for i, n in rows], schema=ROWS_SCHEMA)


async def _batches(*batches: pa.RecordBatch) -> AsyncIterator[pa.RecordBatch]:
    for batch in batches:
        yield batch


def _settings(postgres_config: dict, *, database: str | None = None, **auth: Any) -> dict[str, Any]:
    """Stored settings with inline credentials. `auth` overrides the auth method fields."""
    inline = {key: postgres_config[key] for key in ("host", "port", "user", "password")}
    return {
        "database": database or postgres_config["database"],
        "auth_method": {"selection": "credentials", **inline, **auth},
    }


def _connection(postgres_config: dict, *, database: str | None = None, **auth: Any) -> DestinationConnection:
    config = api.parse_destination_config(
        DestinationType.POSTGRES, _settings(postgres_config, database=database, **auth)
    )
    return DestinationConnection(team_id=1, config=config)


def _destination(postgres_config: dict, **overrides: Any) -> PostgresDestination:
    return PostgresDestination(_connection(postgres_config, **overrides))


def _integration(postgres_config: dict, **config_overrides: Any) -> Integration:
    config = {key: postgres_config[key] for key in ("host", "port", "user")}
    return Integration(
        team_id=1,
        kind="postgresql",
        config={**config, "ssl_mode": "prefer", **config_overrides},
        sensitive_config={"password": postgres_config["password"]},
    )


def _ref(schema: str, table: str, write_mode: WriteMode, **kwargs: Any) -> TargetRef:
    kwargs.setdefault("staging_key", "run1")
    return TargetRef(namespace=kwargs.pop("namespace", (schema,)), table_name=table, write_mode=write_mode, **kwargs)


def _target(schema: str, table: str, write_mode: WriteMode, **kwargs: Any) -> TableTarget:
    if write_mode == WriteMode.MERGE and "merge" not in kwargs:
        kwargs["merge"] = MergeSpec(primary_keys=("id",))
    ref_kwargs = {key: kwargs.pop(key) for key in ("staging_key", "owner_tag", "namespace") if key in kwargs}
    return TableTarget(
        ref=_ref(schema, table, write_mode, **ref_kwargs),
        schema=kwargs.pop("arrow_schema", ROWS_SCHEMA),
        **kwargs,
    )


async def _run(
    destination: PostgresDestination,
    target: TableTarget,
    *batches: pa.RecordBatch,
    batch_key: str | None = None,
    commit: bool = True,
) -> PreparedTarget:
    async with destination.connect() as session:
        prepared = await session.prepare(target)
        await session.write(prepared, _batches(*batches), batch_key=batch_key)
        if commit:
            await session.commit(target)
    return prepared


def _select(pg: psycopg.Connection, schema: str, table: str, columns: str = "id, name") -> list[tuple]:
    return pg.execute(
        sql.SQL("SELECT {} FROM {} ORDER BY 1").format(sql.SQL(columns), sql.Identifier(schema, table))
    ).fetchall()


def _columns(pg: psycopg.Connection, schema: str, table: str) -> dict[str, str]:
    rows = pg.execute(
        """
        SELECT a.attname, format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped
        """,
        (schema, table),
    ).fetchall()
    return dict(rows)


def _exists(pg: psycopg.Connection, schema: str, table: str) -> bool:
    return bool(_columns(pg, schema, table))


def _comment(pg: psycopg.Connection, schema: str, table: str) -> str | None:
    row = pg.execute("SELECT obj_description(%s::regclass)", (sql.Identifier(schema, table).as_string(),)).fetchone()
    return row[0] if row else None


def _create_table(pg: psycopg.Connection, schema: str, table: str, ddl: str, comment: str | None = None) -> None:
    pg.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
    pg.execute(sql.SQL("CREATE TABLE {} ({})").format(sql.Identifier(schema, table), sql.SQL(ddl)))
    if comment is not None:
        pg.execute(sql.SQL("COMMENT ON TABLE {} IS {}").format(sql.Identifier(schema, table), sql.Literal(comment)))


def _staging(table: str = "t", staging_key: str = "run1") -> str:
    return staging_table_name(table, staging_key)


@pytest.mark.parametrize(
    "write_mode, expected",
    [
        (WriteMode.APPEND, [(1, "a"), (2, "b"), (2, "B"), (3, "c")]),
        (WriteMode.MERGE, [(1, "a"), (2, "B"), (3, "c")]),
        (WriteMode.REPLACE, [(2, "B"), (3, "c")]),
    ],
)
async def test_write_modes_end_to_end(postgres_config, pg, schema, write_mode: WriteMode, expected: list) -> None:
    await _run(_destination(postgres_config), _target(schema, "t", write_mode), _rows((1, "a"), (2, "b")))
    second = _target(schema, "t", write_mode, staging_key="run2")
    await _run(_destination(postgres_config), second, _rows((2, "B")), _rows((3, "c")))

    assert _select(pg, schema, "t") == expected
    assert set(_columns(pg, schema, "t")) == {"id", "name"}
    assert not _exists(pg, schema, _staging(staging_key="run2"))


@pytest.mark.parametrize(
    "arrow_type, values, expected_type, expected_values",
    [
        (pa.date32(), [dt.date(2024, 1, 2)], "date", [dt.date(2024, 1, 2)]),
        (pa.decimal128(10, 2), [decimal.Decimal("1.25")], "numeric(10,2)", [decimal.Decimal("1.25")]),
        (pa.binary(), [b"\x00\x01"], "bytea", [b"\x00\x01"]),
        (pa.struct([("a", pa.int64())]), [{"a": 1}], "jsonb", [{"a": 1}]),
        (pa.list_(pa.int64()), [[1, 2]], "jsonb", [[1, 2]]),
        (pa.time64("us"), [dt.time(12, 30)], "time without time zone", [dt.time(12, 30)]),
        (pa.duration("s"), [dt.timedelta(seconds=90)], "interval", [dt.timedelta(seconds=90)]),
    ],
)
async def test_strict_raises_where_permissive_stores_the_value(
    postgres_config, pg, schema, arrow_type: pa.DataType, values: list, expected_type: str, expected_values: list
) -> None:
    arrow_schema = _schema(("id", pa.int64()), ("value", arrow_type))
    batch = pa.RecordBatch.from_pydict({"id": [1], "value": pa.array(values, type=arrow_type)}, schema=arrow_schema)

    with pytest.raises(ColumnTypeMappingError, match="'value'") as exc_info:
        await _run(_destination(postgres_config), _target(schema, "t", WriteMode.APPEND, arrow_schema=arrow_schema))
    assert exc_info.value.kind == ErrorKind.DATA
    assert not _exists(pg, schema, "t")

    permissive = _target(schema, "t", WriteMode.APPEND, arrow_schema=arrow_schema, type_policy=TypePolicy.PERMISSIVE)
    await _run(_destination(postgres_config), permissive, batch)

    assert _columns(pg, schema, "t")["value"] == expected_type
    assert [row[1] for row in _select(pg, schema, "t", "id, value")] == expected_values


@pytest.mark.parametrize(
    "policy, expected_columns, expected_rows",
    [
        (NewColumnPolicy.ADD, {"id", "name", "extra"}, [(1, "a", None), (2, "b", "x")]),
        (NewColumnPolicy.IGNORE, {"id", "name"}, [(1, "a"), (2, "b")]),
    ],
)
async def test_new_columns_policy(
    postgres_config, pg, schema, policy: NewColumnPolicy, expected_columns: set, expected_rows: list
) -> None:
    await _run(_destination(postgres_config), _target(schema, "t", WriteMode.APPEND), _rows((1, "a")))
    wider = pa.schema([*ROWS_SCHEMA, ("extra", pa.string())])
    batch = pa.RecordBatch.from_pylist([{"id": 2, "name": "b", "extra": "x"}], schema=wider)

    await _run(
        _destination(postgres_config),
        _target(schema, "t", WriteMode.APPEND, arrow_schema=wider, new_columns=policy),
        batch,
    )

    assert set(_columns(pg, schema, "t")) == expected_columns
    assert _select(pg, schema, "t", ", ".join(sorted(expected_columns, key=["id", "name", "extra"].index))) == (
        expected_rows
    )


@pytest.mark.parametrize("write_mode", [WriteMode.APPEND, WriteMode.MERGE])
async def test_ignore_with_no_matching_column_raises(postgres_config, pg, schema, write_mode: WriteMode) -> None:
    _create_table(pg, schema, "t", "other TEXT")

    async with _destination(postgres_config).connect() as session:
        with pytest.raises(PostgreSQLIncompatibleSchemaError, match="No matching columns") as exc_info:
            await session.prepare(_target(schema, "t", write_mode, new_columns=NewColumnPolicy.IGNORE))

    assert exc_info.value.kind == ErrorKind.DATA
    assert set(_columns(pg, schema, "t")) == {"other"}
    assert not _exists(pg, schema, _staging())


async def test_column_types_win_over_the_type_policy(postgres_config, pg, schema) -> None:
    arrow_schema = _schema(
        ("id", pa.int64()),
        ("payload", pa.string()),
        ("nested", pa.list_(pa.string())),
        ("amount", pa.decimal128(10, 2)),
        ("uid", pa.string()),
        ("day", pa.date32()),
    )
    batch = pa.RecordBatch.from_pylist(
        [
            {
                "id": 1,
                "payload": '{"a": [1, 2]}',
                "nested": ["x", "y"],
                "amount": decimal.Decimal("3.50"),
                "uid": "6f1c9a2e-0d4b-4c8e-9a51-1b2c3d4e5f60",
                "day": dt.date(2026, 1, 2),
            }
        ],
        schema=arrow_schema,
    )
    target = _target(
        schema,
        "t",
        WriteMode.APPEND,
        arrow_schema=arrow_schema,
        column_types={
            "id": LogicalType.INT32,
            "payload": LogicalType.JSON,
            "nested": LogicalType.JSON,
            "amount": LogicalType.DECIMAL,
            "uid": LogicalType.UUID,
            # date32 is outside the STRICT mapping, so only the pin lets it through.
            "day": LogicalType.DATE,
        },
    )

    await _run(_destination(postgres_config), target, batch)

    assert _columns(pg, schema, "t") == {
        "id": "integer",
        "payload": "jsonb",
        "nested": "jsonb",
        "amount": "numeric(10,2)",
        "uid": "uuid",
        "day": "date",
    }
    row = _select(pg, schema, "t", "id, payload, nested, amount, uid::text, day")[0]
    assert row == (
        1,
        {"a": [1, 2]},
        ["x", "y"],
        decimal.Decimal("3.50"),
        "6f1c9a2e-0d4b-4c8e-9a51-1b2c3d4e5f60",
        dt.date(2026, 1, 2),
    )


@pytest.mark.parametrize(
    "target_kwargs, error, match",
    [
        ({"namespace": ("another_database", "public")}, DestinationConfigurationError, "must have 1 part"),
        ({"namespace": ()}, DestinationConfigurationError, "must have 1 part"),
        ({"table_name": "x" * 64}, PostgreSQLInvalidTargetError, "longer than 63 bytes"),
        (
            {"arrow_schema": _schema(("id", pa.int64()), (BATCH_KEY_COLUMN, pa.string()))},
            PostgreSQLInvalidTargetError,
            "reserved",
        ),
        # Postgres would truncate the name, and later writes would drop the column.
        (
            {"arrow_schema": _schema(("id", pa.int64()), ("c" * 64, pa.string()))},
            PostgreSQLIncompatibleSchemaError,
            "longer than 63 bytes",
        ),
    ],
)
async def test_invalid_target_is_refused_before_any_change(
    postgres_config, pg, schema, target_kwargs: dict, error: type[Exception], match: str
) -> None:
    table = target_kwargs.pop("table_name", "t")
    target = _target(schema, table, WriteMode.APPEND, **target_kwargs)

    async with _destination(postgres_config).connect() as session:
        with pytest.raises(error, match=match) as exc_info:
            await session.prepare(target)

    assert isinstance(exc_info.value, DestinationError)
    assert not exc_info.value.retryable
    assert pg.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone() is None


@pytest.mark.parametrize(
    "staged_version, expected",
    [
        (3, [(1, 5, "kept"), (2, 1, "new row")]),
        (7, [(1, 7, "updated"), (2, 1, "new row")]),
    ],
)
async def test_version_key_merge_updates_only_newer_rows(
    postgres_config, pg, schema, staged_version: int, expected: list
) -> None:
    arrow_schema = _schema(("id", pa.int64()), ("version", pa.int64()), ("name", pa.string()))
    merge = MergeSpec(primary_keys=("id",), version_keys=("version",))

    def batch(*rows: tuple[int, int, str]) -> pa.RecordBatch:
        return pa.RecordBatch.from_pylist([{"id": i, "version": v, "name": n} for i, v, n in rows], schema=arrow_schema)

    await _run(
        _destination(postgres_config),
        _target(schema, "t", WriteMode.MERGE, arrow_schema=arrow_schema, merge=merge),
        batch((1, 5, "kept")),
    )
    await _run(
        _destination(postgres_config),
        _target(schema, "t", WriteMode.MERGE, arrow_schema=arrow_schema, merge=merge, staging_key="run2"),
        batch((1, staged_version, "kept" if staged_version < 5 else "updated"), (2, 1, "new row")),
    )

    assert _select(pg, schema, "t", "id, version, name") == expected


@pytest.mark.parametrize("version_keys", [(), ("version",)])
@pytest.mark.parametrize("ensure_unique_key", [True, False])
@pytest.mark.parametrize(
    "index, usable",
    [
        (None, False),
        # ON CONFLICT (id) cannot use a partial index or one with an expression.
        ("(id) WHERE id > 0", False),
        ("(id, lower(name))", False),
        # INCLUDE columns are not key columns, so this index is a unique key on id alone.
        ("(id) INCLUDE (name)", True),
    ],
)
async def test_ensure_unique_key_decides_for_a_table_without_one(
    postgres_config, pg, schema, ensure_unique_key: bool, version_keys: tuple, index: str | None, usable: bool
) -> None:
    _create_table(pg, schema, "t", "id BIGINT, version BIGINT, name TEXT")
    if index is not None:
        pg.execute(sql.SQL("CREATE UNIQUE INDEX ON {} {}").format(sql.Identifier(schema, "t"), sql.SQL(index)))
    pg.execute(sql.SQL("INSERT INTO {} VALUES (1, 1, 'a')").format(sql.Identifier(schema, "t")))
    arrow_schema = _schema(("id", pa.int64()), ("version", pa.int64()), ("name", pa.string()))
    batch = pa.RecordBatch.from_pylist([{"id": 1, "version": 2, "name": "b"}], schema=arrow_schema)
    merge = MergeSpec(primary_keys=("id",), version_keys=version_keys, ensure_unique_key=ensure_unique_key)
    target = _target(schema, "t", WriteMode.MERGE, arrow_schema=arrow_schema, merge=merge)

    if ensure_unique_key or usable:
        await _run(_destination(postgres_config), target, batch)
        await _run(_destination(postgres_config), target, batch)
        assert _select(pg, schema, "t", "id, version, name") == [(1, 2, "b")]
    else:
        with pytest.raises(MissingPrimaryKeyError) as exc_info:
            await _run(_destination(postgres_config), target, batch)
        assert exc_info.value.kind == ErrorKind.DATA
        assert _select(pg, schema, "t", "id, version, name") == [(1, 1, "a")]
        assert not _exists(pg, schema, _staging())


@pytest.mark.parametrize(
    "version_keys, writes, expected",
    [
        ((), [(1, 1, "a"), (1, 1, "b")], [(1, 1, "b")]),
        (("version",), [(1, 2, "newer"), (1, 1, "older")], [(1, 2, "newer")]),
        (("version",), [(1, None, "null version"), (1, 1, "versioned")], [(1, 1, "versioned")]),
    ],
)
async def test_dedupe_source_keeps_one_row_per_key_across_writes(
    postgres_config, pg, schema, version_keys: tuple, writes: list, expected: list
) -> None:
    arrow_schema = _schema(("id", pa.int64()), ("version", pa.int64()), ("name", pa.string()))
    target = _target(
        schema,
        "t",
        WriteMode.MERGE,
        arrow_schema=arrow_schema,
        merge=MergeSpec(primary_keys=("id",), version_keys=version_keys, dedupe_source=True),
    )

    async with _destination(postgres_config).connect() as session:
        prepared = await session.prepare(target)
        for index, (i, v, n) in enumerate(writes):
            batch = pa.RecordBatch.from_pylist([{"id": i, "version": v, "name": n}], schema=arrow_schema)
            await session.write(prepared, _batches(batch), batch_key=str(index))
        await session.commit(target)

    assert _select(pg, schema, "t", "id, version, name") == expected


async def test_duplicate_keys_without_dedupe_source_are_a_data_error(postgres_config, schema) -> None:
    with pytest.raises(DestinationError) as exc_info:
        await _run(_destination(postgres_config), _target(schema, "t", WriteMode.MERGE), _rows((1, "a"), (1, "b")))

    assert exc_info.value.kind == ErrorKind.DATA
    assert isinstance(exc_info.value.__cause__, psycopg.errors.CardinalityViolation)


@pytest.mark.parametrize("write_mode", list(WriteMode))
async def test_retried_write_with_the_same_batch_key_does_not_duplicate(
    postgres_config, pg, schema, write_mode: WriteMode
) -> None:
    target = _target(schema, "t", write_mode)

    async with _destination(postgres_config).connect() as session:
        prepared = await session.prepare(target)
        await session.write(prepared, _batches(_rows((1, "a"), (2, "b"))), batch_key="0")
        await session.write(prepared, _batches(_rows((1, "a"), (2, "b"))), batch_key="0")
        await session.write(prepared, _batches(_rows((3, "c"))), batch_key="1")

        assert pg.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(schema, _staging()))).fetchone() == (
            3,
        )
        await session.commit(target)

    assert _select(pg, schema, "t") == [(1, "a"), (2, "b"), (3, "c")]
    assert BATCH_KEY_COLUMN not in _columns(pg, schema, "t")


async def test_concurrent_sessions_write_distinct_batch_keys_into_one_staging_key(postgres_config, pg, schema) -> None:
    target = _target(schema, "t", WriteMode.MERGE)
    destination = _destination(postgres_config)

    async def write(batch_key: str, *rows: tuple[int, str]) -> None:
        async with destination.connect() as session:
            prepared = await session.prepare(target)
            await session.write(prepared, _batches(_rows(*rows)), batch_key=batch_key)

    await asyncio.gather(write("0", (1, "a"), (2, "b")), write("1", (3, "c")), write("2", (4, "d")))
    async with destination.connect() as session:
        await session.commit(target)

    assert _select(pg, schema, "t") == [(1, "a"), (2, "b"), (3, "c"), (4, "d")]


@pytest.mark.parametrize("write_mode", list(WriteMode))
async def test_prepare_again_resumes_the_staging_table(postgres_config, pg, schema, write_mode: WriteMode) -> None:
    await _run(_destination(postgres_config), _target(schema, "t", write_mode), _rows((1, "a")), commit=False)

    await _run(_destination(postgres_config), _target(schema, "t", write_mode), _rows((2, "b")))

    assert _select(pg, schema, "t") == [(1, "a"), (2, "b")]
    assert not _exists(pg, schema, _staging())


@pytest.mark.parametrize("write_mode", [WriteMode.APPEND, WriteMode.MERGE])
@pytest.mark.parametrize(
    "added_to_final, value, expected",
    [
        # The second prepare adds the column to the final table from the data's type.
        (None, "x", "x"),
        # Someone else added it with another type. The staging copy must take that type, or the
        # commit reads text into a BIGINT column.
        ("BIGINT", "7", 7),
    ],
)
async def test_resumed_staging_gains_columns_added_to_the_final_table(
    postgres_config, pg, schema, write_mode: WriteMode, added_to_final: str | None, value: str, expected: Any
) -> None:
    await _run(_destination(postgres_config), _target(schema, "t", write_mode), _rows((1, "a")), commit=False)
    if added_to_final is not None:
        pg.execute(
            sql.SQL("ALTER TABLE {} ADD COLUMN extra {}").format(sql.Identifier(schema, "t"), sql.SQL(added_to_final))
        )
    wider = pa.schema([*ROWS_SCHEMA, ("extra", pa.string())])
    batch = pa.RecordBatch.from_pylist([{"id": 2, "name": "b", "extra": value}], schema=wider)

    await _run(_destination(postgres_config), _target(schema, "t", write_mode, arrow_schema=wider), batch)

    assert _select(pg, schema, "t", "id, name, extra") == [(1, "a", None), (2, "b", expected)]


@pytest.mark.parametrize(
    "write_mode, expected",
    [
        (WriteMode.APPEND, [(1, "a", "mine"), (2, "c", "default")]),
        (WriteMode.MERGE, [(1, "b", "mine"), (2, "c", "default")]),
    ],
)
async def test_a_column_that_only_the_final_table_has_keeps_its_value(
    postgres_config, pg, schema, write_mode: WriteMode, expected: list
) -> None:
    _create_table(pg, schema, "t", "id BIGINT PRIMARY KEY, name TEXT, note TEXT NOT NULL DEFAULT 'default'")
    pg.execute(sql.SQL("INSERT INTO {} VALUES (1, 'a', 'mine')").format(sql.Identifier(schema, "t")))
    rows = _rows((1, "b"), (2, "c")) if write_mode == WriteMode.MERGE else _rows((2, "c"))

    await _run(_destination(postgres_config), _target(schema, "t", write_mode), rows)

    assert _select(pg, schema, "t", "id, name, note") == expected


@pytest.mark.parametrize("write_mode", list(WriteMode))
async def test_staging_tables_index_the_batch_key_also_when_resumed(
    postgres_config, pg, schema, write_mode: WriteMode
) -> None:
    index = batch_key_index_name(_staging())
    index_query = "SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND indexname = %s"

    for _ in range(2):
        async with _destination(postgres_config).connect() as session:
            await session.prepare(_target(schema, "t", write_mode))

        row = pg.execute(index_query, (schema, index)).fetchone()
        assert row is not None and f"({BATCH_KEY_COLUMN})" in row[0]
        # The next prepare resumes a staging table without the index, as an older one would be.
        pg.execute(sql.SQL("DROP INDEX {}").format(sql.Identifier(schema, index)))


async def test_a_serialization_failure_after_the_copy_read_its_data_still_writes_every_row(
    postgres_config, pg, schema
) -> None:
    target = _target(schema, "t", WriteMode.APPEND)

    async with _destination(postgres_config).connect() as session:
        prepared = await session.prepare(target)
        attempts = sql.Identifier(schema, "attempts")
        pg.execute(sql.SQL("CREATE SEQUENCE {}").format(attempts))
        # The sequence is not transactional, so only the first COPY fails, and only on its first row.
        pg.execute(
            sql.SQL(
                "CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                "IF nextval({}) = 1 THEN RAISE EXCEPTION 'conflict' USING ERRCODE = 'serialization_failure'; END IF; "
                "RETURN NEW; END $$"
            ).format(sql.Identifier(schema, "fail_once"), sql.Literal(attempts.as_string()))
        )
        pg.execute(
            sql.SQL("CREATE TRIGGER fail_once BEFORE INSERT ON {} FOR EACH ROW EXECUTE FUNCTION {}()").format(
                sql.Identifier(schema, _staging()), sql.Identifier(schema, "fail_once")
            )
        )
        await session.write(prepared, _batches(_rows((1, "a"), (2, "b"))))
        await session.commit(target)

    assert _select(pg, schema, "t") == [(1, "a"), (2, "b")]


@pytest.mark.parametrize("write_mode", [WriteMode.APPEND, WriteMode.MERGE, WriteMode.REPLACE])
async def test_commit_twice_is_safe(postgres_config, pg, schema, write_mode: WriteMode) -> None:
    target = _target(schema, "t", write_mode)

    async with _destination(postgres_config).connect() as session:
        prepared = await session.prepare(target)
        await session.write(prepared, _batches(_rows((1, "a"))))
        await session.commit(target)
        await session.commit(target)

    assert _select(pg, schema, "t") == [(1, "a")]


@pytest.mark.parametrize(
    "write_mode, expected_after_each",
    [
        (
            WriteMode.APPEND,
            [
                [(1, "a"), (2, "b")],
                [(1, "a"), (2, "B"), (2, "b"), (3, "c")],
                [(1, "A"), (1, "a"), (2, "B"), (2, "b"), (3, "c")],
            ],
        ),
        (
            WriteMode.MERGE,
            [
                [(1, "a"), (2, "b")],
                [(1, "a"), (2, "B"), (3, "c")],
                [(1, "A"), (2, "B"), (3, "c")],
            ],
        ),
    ],
)
async def test_commits_per_batch_reuse_the_staging_table(
    postgres_config, pg, schema, write_mode: WriteMode, expected_after_each: list
) -> None:
    target = _target(schema, "t", write_mode)
    batches = [
        _rows((1, "a"), (2, "b")),
        _rows((2, "B"), (3, "c")),
        _rows((1, "A")),
    ]

    async with _destination(postgres_config).connect() as session:
        prepared = await session.prepare(target)
        for index, (batch, expected) in enumerate(zip(batches, expected_after_each)):
            before = _select(pg, schema, "t")
            await session.write(prepared, _batches(batch), batch_key=str(index))
            assert _select(pg, schema, "t") == before

            await session.commit(target, final=False)

            assert sorted(_select(pg, schema, "t")) == expected
            assert _select(pg, schema, _staging()) == []

        await session.commit(target, final=True)

    assert sorted(_select(pg, schema, "t")) == expected_after_each[-1]
    assert not _exists(pg, schema, _staging())


async def test_replace_commit_that_is_not_final_changes_nothing(postgres_config, pg, schema) -> None:
    await _run(_destination(postgres_config), _target(schema, "t", WriteMode.REPLACE), _rows((1, "old")))
    target = _target(schema, "t", WriteMode.REPLACE, staging_key="run2")

    async with _destination(postgres_config).connect() as session:
        prepared = await session.prepare(target)
        await session.write(prepared, _batches(_rows((2, "new"))))
        await session.commit(target, final=False)

        assert _select(pg, schema, "t") == [(1, "old")]
        assert _select(pg, schema, _staging(staging_key="run2")) == [(2, "new")]

        await session.commit(target)

    assert _select(pg, schema, "t") == [(2, "new")]


async def test_a_swap_that_waits_too_long_for_a_reader_is_a_transient_error(postgres_config, pg, schema) -> None:
    await _run(_destination(postgres_config), _target(schema, "t", WriteMode.REPLACE), _rows((1, "a")))
    target = _target(schema, "t", WriteMode.REPLACE, staging_key="run2")
    destination = PostgresDestination(_connection(postgres_config), swap_lock_timeout_seconds=0.2)
    await _run(destination, target, _rows((2, "b")), commit=False)

    with psycopg.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        host=postgres_config["host"],
        port=postgres_config["port"],
        dbname=postgres_config["database"],
    ) as reader:
        # The open transaction keeps its lock on the final table until the rollback.
        reader.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(schema, "t")))
        with pytest.raises(DestinationError) as exc_info:
            async with destination.connect() as session:
                await session.commit(target)
        reader.rollback()

    assert exc_info.value.kind == ErrorKind.TRANSIENT
    assert isinstance(exc_info.value.__cause__, psycopg.errors.LockNotAvailable)
    assert _select(pg, schema, "t") == [(1, "a")]

    async with destination.connect() as session:
        await session.commit(target)
    assert _select(pg, schema, "t") == [(2, "b")]


@pytest.mark.parametrize("write_mode", list(WriteMode))
async def test_a_new_session_commits_without_prepare(postgres_config, pg, schema, write_mode: WriteMode) -> None:
    await _run(
        _destination(postgres_config),
        _target(schema, "t", write_mode, owner_tag="owner"),
        _rows((1, "a")),
        batch_key="0",
        commit=False,
    )

    async with _destination(postgres_config).connect() as session:
        await session.commit(_target(schema, "t", write_mode, owner_tag="owner"))

    assert _select(pg, schema, "t") == [(1, "a")]
    assert not _exists(pg, schema, _staging())


@pytest.mark.parametrize("write_mode", [WriteMode.APPEND, WriteMode.MERGE, WriteMode.REPLACE])
@pytest.mark.parametrize("method", ["abort", "commit"])
async def test_abort_and_commit_without_prepare_do_nothing(
    postgres_config, pg, schema, write_mode: WriteMode, method: str
) -> None:
    target = _target(schema, "t", write_mode)

    async with _destination(postgres_config).connect() as session:
        if method == "abort":
            await session.abort(target.ref)
        else:
            await session.commit(target)

    assert pg.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone() is None


async def test_abort_never_raises_for_an_invalid_ref(postgres_config, schema) -> None:
    async with _destination(postgres_config).connect() as session:
        await session.abort(_ref(schema, "t", WriteMode.MERGE, namespace=("too", "deep")))


@pytest.mark.parametrize("write_mode", list(WriteMode))
async def test_abort_drops_the_staging_table_and_keeps_the_final_table(
    postgres_config, pg, schema, write_mode: WriteMode
) -> None:
    await _run(_destination(postgres_config), _target(schema, "t", write_mode), _rows((1, "a")))
    await _run(
        _destination(postgres_config),
        _target(schema, "t", write_mode, staging_key="run2"),
        _rows((2, "b")),
        commit=False,
    )

    async with _destination(postgres_config).connect() as session:
        await session.abort(_ref(schema, "t", write_mode, staging_key="run2"))
        await session.abort(_ref(schema, "t", write_mode, staging_key="run2"))

    assert not _exists(pg, schema, _staging(staging_key="run2"))
    assert _select(pg, schema, "t") == [(1, "a")]


@pytest.mark.parametrize("write_mode", list(WriteMode))
@pytest.mark.parametrize(
    "existing_comment, allowed",
    [
        (None, False),
        ("someone else", False),
        ("owner-tag123", False),
        ("owner-tag:child", False),
        (table_marker.encode("other"), False),
        ("owner-tag", True),
        (table_marker.encode("owner-tag"), True),
    ],
)
async def test_an_owner_tag_refuses_an_existing_table_without_it(
    postgres_config, pg, schema, write_mode: WriteMode, existing_comment: str | None, allowed: bool
) -> None:
    _create_table(pg, schema, "t", "id BIGINT PRIMARY KEY, name TEXT", comment=existing_comment)
    pg.execute(sql.SQL("INSERT INTO {} VALUES (0, 'old')").format(sql.Identifier(schema, "t")))
    # The extra column makes an accepted write alter the final table.
    wider = pa.schema([*ROWS_SCHEMA, ("extra", pa.string())])
    batch = pa.RecordBatch.from_pylist([{"id": 1, "name": "a", "extra": "x"}], schema=wider)
    target = _target(schema, "t", write_mode, owner_tag="owner-tag", arrow_schema=wider)

    if allowed:
        await _run(_destination(postgres_config), target, batch)
        expected = [(1, "a")] if write_mode == WriteMode.REPLACE else [(0, "old"), (1, "a")]
        assert _select(pg, schema, "t") == expected
    else:
        with pytest.raises(PostgreSQLUnrelatedTableError) as exc_info:
            await _run(_destination(postgres_config), target, batch)
        assert exc_info.value.kind == ErrorKind.CONFIGURATION
        assert _select(pg, schema, "t") == [(0, "old")]
        assert set(_columns(pg, schema, "t")) == {"id", "name"}
        assert not _exists(pg, schema, _staging())


@pytest.mark.parametrize("write_mode", list(WriteMode))
@pytest.mark.parametrize("existing_comment", ["someone else", table_marker.encode("other")])
async def test_no_owner_tag_writes_to_a_table_someone_else_created(
    postgres_config, pg, schema, write_mode: WriteMode, existing_comment: str
) -> None:
    _create_table(pg, schema, "t", "id BIGINT PRIMARY KEY, name TEXT", comment=existing_comment)

    await _run(_destination(postgres_config), _target(schema, "t", write_mode), _rows((1, "a")))

    assert _select(pg, schema, "t") == [(1, "a")]


@pytest.mark.parametrize("write_mode", list(WriteMode))
async def test_the_owner_tag_is_checked_again_when_the_commit_runs(
    postgres_config, pg, schema, write_mode: WriteMode
) -> None:
    target = _target(schema, "t", write_mode, owner_tag="owner")

    async with _destination(postgres_config).connect() as session:
        prepared = await session.prepare(target)
        await session.write(prepared, _batches(_rows((1, "a"))))
        pg.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(schema, "t")))
        _create_table(pg, schema, "t", "id BIGINT PRIMARY KEY, name TEXT", comment="created meanwhile")

        with pytest.raises(PostgreSQLUnrelatedTableError):
            await session.commit(target)

    assert _select(pg, schema, "t") == []
    assert _exists(pg, schema, _staging())


async def test_a_prepare_that_loses_the_create_race_does_not_take_the_table(postgres_config, pg, schema) -> None:
    pg.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    destination = _destination(postgres_config)

    with psycopg.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        host=postgres_config["host"],
        port=postgres_config["port"],
        dbname=postgres_config["database"],
    ) as first:
        # Another prepare holds the create lock and has created its table, but not committed yet.
        first.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (_lock_key(schema, "t"),))
        first.execute(sql.SQL("CREATE TABLE {} (id BIGINT, name TEXT)").format(sql.Identifier(schema, "t")))
        first.execute(
            sql.SQL("COMMENT ON TABLE {} IS {}").format(
                sql.Identifier(schema, "t"), sql.Literal(table_marker.encode("first"))
            )
        )

        async with destination.connect() as session:
            assert isinstance(session, PostgresSession)
            pid = session._client().connection.info.backend_pid
            second = asyncio.create_task(session.prepare(_target(schema, "t", WriteMode.APPEND, owner_tag="second")))

            def waits_for_the_lock() -> bool:
                row = pg.execute("SELECT count(*) FROM pg_locks WHERE pid = %s AND NOT granted", (pid,)).fetchone()
                return row is not None and row[0] > 0

            await asyncio.to_thread(wait_until, waits_for_the_lock)
            first.commit()

            with pytest.raises(PostgreSQLUnrelatedTableError):
                await second

    assert table_marker.parse(_comment(pg, schema, "t")) == "first"
    assert not _exists(pg, schema, _staging())


@pytest.mark.parametrize("write_mode", list(WriteMode))
@pytest.mark.parametrize("owner_tag", ["owner", None])
async def test_final_tables_this_destination_creates_carry_the_owner_tag(
    postgres_config, pg, schema, write_mode: WriteMode, owner_tag: str | None
) -> None:
    await _run(_destination(postgres_config), _target(schema, "t", write_mode, owner_tag=owner_tag), _rows((1, "a")))

    comment = _comment(pg, schema, "t")
    assert (table_marker.parse(comment) if owner_tag else comment) == owner_tag


@pytest.mark.parametrize(
    "base, suffix",
    [
        ("events", "__ph_stage_run1"),
        ("x" * 63, "__ph_stage_run1"),
        ("é" * 40, "__ph_stage_run1"),
    ],
)
def test_scoped_identifier_fits_postgres_identifiers(base: str, suffix: str) -> None:
    name = scoped_identifier(base, suffix)
    other = scoped_identifier(base, suffix + "x")

    assert len(name.encode()) <= 63
    assert name != other
    assert name not in (base, other)
    assert name == scoped_identifier(base, suffix)


@pytest.mark.parametrize(
    "first, second",
    [
        # The separator can sit in either part, so the readable form alone reads the same.
        (("a", "b__ph_stage_c"), ("a__ph_stage_b", "c")),
        (("t" * 63, "run1"), ("t" * 63, "run2")),
        (("é" * 40, "run1"), ("é" * 40, "run1x")),
    ],
)
def test_distinct_tables_and_staging_keys_get_distinct_staging_names(
    first: tuple[str, str], second: tuple[str, str]
) -> None:
    names = [staging_table_name(*first), staging_table_name(*second)]

    assert names[0] != names[1]
    assert all(len(name.encode()) <= 63 for name in names)
    assert names == [staging_table_name(*first), staging_table_name(*second)]


async def test_a_table_name_at_the_identifier_limit_merges_through_a_distinct_staging_table(
    postgres_config, pg, schema
) -> None:
    table = "t" * 63

    await _run(_destination(postgres_config), _target(schema, table, WriteMode.MERGE), _rows((1, "a")))
    await _run(
        _destination(postgres_config), _target(schema, table, WriteMode.MERGE, staging_key="run2"), _rows((1, "b"))
    )

    assert _select(pg, schema, table) == [(1, "b")]
    assert pg.execute(
        "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE nspname = %s AND relkind = 'r'",
        (schema,),
    ).fetchall() == [(table,)]


@pytest.mark.parametrize("json_type", [JsonType(), _OtherJsonType(), pa.json_()], ids=["own", "other", "canonical"])
async def test_json_and_text_values_round_trip(postgres_config, pg, schema, json_type: pa.DataType) -> None:
    arrow_schema = _schema(
        ("id", pa.int64()),
        ("properties", json_type),
        ("tags", pa.list_(pa.string())),
        ("text", pa.string()),
    )
    properties = {"nested": {"a": [1, 2]}, "quote": 'say "hi"', "tab": "a\tb", "null": "\u0000"}
    # Postgres refuses an empty text and a raw newline inside a JSON string as JSON input.
    unescaped_newline = '{"line": "a\nb"}'
    # Valid JSON keeps its structure and exact numbers: a float would round the big integer.
    formatted = '{\n\t"n": 18446744073709551617,\n\t"list": [\n1,\n2\n]\n}'
    formatted_array = "[\n1,\n2\n]"
    batch = pa.RecordBatch.from_arrays(
        [
            pa.array([1, 2, 3, 4, 5, 6]),
            pa.ExtensionArray.from_storage(
                typing.cast(pa.BaseExtensionType, json_type),
                pa.array([json.dumps(properties), None, "", unescaped_newline, formatted, formatted_array]),
            ),
            pa.array([["a", "{b}"], [], None, None, None, None], type=pa.list_(pa.string())),
            pa.array(['line\nbreak\t"quoted"', "", None, None, None, None]),
        ],
        schema=arrow_schema,
    )

    await _run(_destination(postgres_config), _target(schema, "t", WriteMode.APPEND, arrow_schema=arrow_schema), batch)

    assert _columns(pg, schema, "t") == {"id": "bigint", "properties": "jsonb", "tags": "text[]", "text": "text"}
    assert _select(pg, schema, "t", "id, properties, tags, text") == [
        (1, {**properties, "null": ""}, ["a", "{b}"], 'line\nbreak\t"quoted"'),
        (2, None, [], ""),
        (3, None, None, None),
        (4, {"line": "a\nb"}, None, None),
        (5, {"n": 18446744073709551617, "list": [1, 2]}, None, None),
        (6, [1, 2], None, None),
    ]


async def test_probes_leave_the_connection_idle(postgres_config, schema) -> None:
    async with _destination(postgres_config).connect() as session:
        await session.prepare(_target(schema, "t", WriteMode.MERGE, owner_tag="owner-tag"))

        assert isinstance(session, PostgresSession)
        assert session._client().connection.pgconn.transaction_status == psycopg.pq.TransactionStatus.IDLE


async def test_a_closed_session_raises_a_configuration_error(postgres_config, schema) -> None:
    async with _destination(postgres_config).connect() as session:
        pass

    with pytest.raises(DestinationError, match="session is closed") as exc_info:
        await session.prepare(_target(schema, "t", WriteMode.APPEND))
    assert exc_info.value.kind == ErrorKind.CONFIGURATION


@pytest.mark.parametrize(
    "overrides",
    [
        {"password": "wrong"},
        {"user": "no_such_role"},
        {"database": "no_such_database"},
        {"host": "no-such-host.invalid"},
    ],
)
async def test_bad_connection_settings_are_configuration_errors(postgres_config, overrides: dict) -> None:
    with pytest.raises(PostgreSQLConnectionConfigurationError) as exc_info:
        async with _destination(postgres_config, **overrides).connect():
            pass

    assert exc_info.value.kind == ErrorKind.CONFIGURATION
    assert exc_info.value.detail
    assert "wrong" not in exc_info.value.detail


@pytest.mark.parametrize("missing_key", ["host", "port", "user", "ssl_mode"])
async def test_an_integration_without_required_inputs_is_a_configuration_error(
    postgres_config, monkeypatch: pytest.MonkeyPatch, missing_key: str
) -> None:
    integration = _integration(postgres_config)
    del integration.config[missing_key]

    async def aget(team_id: int, integration_id: int) -> Integration:
        return integration

    monkeypatch.setattr(IntegrationManager.postgresql.credentials, "aget", aget)

    with pytest.raises(PostgreSQLMissingRequiredInputsError) as exc_info:
        async with _destination(postgres_config, selection="integration", integration_id=42).connect():
            pass

    assert exc_info.value.kind == ErrorKind.CONFIGURATION


async def test_a_config_of_another_destination_is_a_configuration_error() -> None:
    destination = PostgresDestination(DestinationConnection(team_id=1, config=fake_config(DestinationType.POSTGRES)))

    with pytest.raises(DestinationConfigurationError, match="needs a PostgresDestinationConfig"):
        async with destination.connect():
            pass


async def test_an_error_raised_inside_the_session_passes_through(postgres_config) -> None:
    with pytest.raises(KeyError):
        async with _destination(postgres_config).connect():
            raise KeyError("caller bug")


async def test_missing_privilege_is_a_configuration_error(postgres_config, pg, schema, test_roles) -> None:
    _create_table(pg, schema, "t", "id BIGINT, name TEXT")
    destination = _destination(postgres_config, user=test_roles["limited"], password=ROLE_PASSWORD)

    with pytest.raises(DestinationError) as exc_info:
        await _run(destination, _target(schema, "t", WriteMode.APPEND), _rows((1, "a")))

    assert exc_info.value.kind == ErrorKind.CONFIGURATION
    assert exc_info.value.detail == PERMISSIONS_DETAIL
    assert isinstance(exc_info.value.__cause__, psycopg.errors.InsufficientPrivilege)


@pytest.mark.parametrize(
    "ddl, batch",
    [
        ("id BIGINT, name INTEGER", _rows((1, "not a number"))),
        ("id BIGINT, name TEXT NOT NULL", pa.RecordBatch.from_pylist([{"id": 1, "name": None}], schema=ROWS_SCHEMA)),
        ("id BIGINT, name VARCHAR(2)", _rows((1, "too long"))),
    ],
)
async def test_values_the_table_refuses_are_data_errors(postgres_config, pg, schema, ddl: str, batch) -> None:
    _create_table(pg, schema, "t", ddl)

    with pytest.raises(DestinationError) as exc_info:
        await _run(_destination(postgres_config), _target(schema, "t", WriteMode.APPEND), batch)

    assert exc_info.value.kind == ErrorKind.DATA
    assert not exc_info.value.retryable
    assert isinstance(exc_info.value.__cause__, psycopg.Error)
    # Postgres quotes a refused value in its message, and the detail reaches the customer.
    assert exc_info.value.detail
    for value in batch.column("name").to_pylist():
        assert value is None or value not in exc_info.value.detail


async def test_a_statement_timeout_is_a_timeout_error(postgres_config, pg, schema, test_roles) -> None:
    target = _target(schema, "t", WriteMode.APPEND)
    async with _destination(postgres_config).connect() as session:
        await session.prepare(target)
    pg.execute(
        sql.SQL(
            "CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(2); RETURN NEW; END $$"
        ).format(sql.Identifier(schema, "slow"))
    )
    pg.execute(
        sql.SQL("CREATE TRIGGER slow BEFORE INSERT ON {} FOR EACH ROW EXECUTE FUNCTION {}()").format(
            sql.Identifier(schema, _staging()), sql.Identifier(schema, "slow")
        )
    )
    role = sql.Identifier(test_roles["slow"])
    pg.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(schema), role))
    pg.execute(sql.SQL("GRANT ALL ON ALL TABLES IN SCHEMA {} TO {}").format(sql.Identifier(schema), role))
    destination = _destination(postgres_config, user=test_roles["slow"], password=ROLE_PASSWORD)

    with pytest.raises(DestinationError) as exc_info:
        await _run(destination, target, _rows((1, "a")), commit=False)

    assert exc_info.value.kind == ErrorKind.TIMEOUT
    assert isinstance(exc_info.value.__cause__, psycopg.errors.QueryCanceled)


async def test_a_dropped_connection_is_a_transient_error(postgres_config, pg, schema) -> None:
    async with _destination(postgres_config).connect() as session:
        assert isinstance(session, PostgresSession)
        pid = session._client().connection.info.backend_pid
        pg.execute("SELECT pg_terminate_backend(%s)", (pid,))

        with pytest.raises(DestinationError) as exc_info:
            await session.prepare(_target(schema, "t", WriteMode.APPEND))

    assert exc_info.value.kind == ErrorKind.TRANSIENT
    assert exc_info.value.retryable


async def test_integration_credentials_win_over_inline_values(
    postgres_config, pg, schema, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def aget(team_id: int, integration_id: int) -> Integration:
        assert (team_id, integration_id) == (1, 42)
        return _integration(postgres_config)

    monkeypatch.setattr(IntegrationManager.postgresql.credentials, "aget", aget)
    destination = _destination(postgres_config, selection="integration", integration_id=42, password="wrong")

    await _run(destination, _target(schema, "t", WriteMode.APPEND), _rows((1, "a")))

    assert _select(pg, schema, "t") == [(1, "a")]


async def test_a_missing_integration_is_a_configuration_error(postgres_config, monkeypatch: pytest.MonkeyPatch) -> None:
    async def aget(team_id: int, integration_id: int) -> Integration:
        raise IntegrationNotFound("gone")

    monkeypatch.setattr(IntegrationManager.postgresql.credentials, "aget", aget)

    with pytest.raises(PostgreSQLIntegrationNotFoundError) as exc_info:
        async with _destination(postgres_config, selection="integration", integration_id=42).connect():
            pass
    assert exc_info.value.kind == ErrorKind.CONFIGURATION


def test_the_facade_resolves_the_builtin_postgres_destination() -> None:
    config = api.parse_destination_config(
        DestinationType.POSTGRES, {"database": "db", "auth_method": {"selection": "integration", "integration_id": 1}}
    )
    destination = api.get_destination(DestinationConnection(team_id=1, config=config))

    assert isinstance(destination, PostgresDestination)
    assert destination.capabilities is api.get_capabilities(DestinationType.POSTGRES)
    assert DestinationType.POSTGRES in api.supported_destination_types()
