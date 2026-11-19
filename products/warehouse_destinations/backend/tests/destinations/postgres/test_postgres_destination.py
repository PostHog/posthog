import json
import decimal
import datetime as dt
from collections.abc import AsyncIterator

import pytest

import psycopg
import pyarrow as pa
from psycopg import sql

from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models import Integration

from products.warehouse_destinations.backend.core.json_type import JsonType
from products.warehouse_destinations.backend.destinations.postgres.destination import (
    BATCH_KEY_COLUMN,
    PostgresDestination,
    scoped_identifier,
    staging_table_name,
)
from products.warehouse_destinations.backend.destinations.postgres.errors import (
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
    MergeSpec,
    PreparedTarget,
    TableTarget,
)
from products.warehouse_destinations.backend.facade.enums import NewColumnPolicy, TypePolicy, WriteMode

ROWS_SCHEMA = pa.schema([("id", pa.int64()), ("name", pa.string())])


def _rows(*rows: tuple[int, str]) -> pa.RecordBatch:
    return pa.RecordBatch.from_pylist([{"id": i, "name": n} for i, n in rows], schema=ROWS_SCHEMA)


async def _batches(*batches: pa.RecordBatch) -> AsyncIterator[pa.RecordBatch]:
    for batch in batches:
        yield batch


def _connection(postgres_config: dict, **overrides: object) -> DestinationConnection:
    config = {key: postgres_config[key] for key in ("host", "port", "database")}
    credentials = {key: postgres_config[key] for key in ("user", "password")}
    return DestinationConnection(
        destination_type="Postgres",
        team_id=1,
        config={**config, **overrides.pop("config", {})},
        credentials={**credentials, **overrides.pop("credentials", {})},
        **overrides,
    )


def _destination(postgres_config: dict, **overrides: object) -> PostgresDestination:
    return PostgresDestination(_connection(postgres_config, **overrides))


def _target(schema: str, table: str, write_mode: WriteMode, **kwargs: object) -> TableTarget:
    if write_mode == WriteMode.MERGE and "merge" not in kwargs:
        kwargs["merge"] = MergeSpec(primary_keys=("id",))
    if write_mode != WriteMode.APPEND and "staging_key" not in kwargs:
        kwargs["staging_key"] = "run1"
    return TableTarget(
        namespace=kwargs.pop("namespace", ("warehouse_destinations_test", schema)),
        table_name=kwargs.pop("table_name", table),
        schema=kwargs.pop("arrow_schema", ROWS_SCHEMA),
        write_mode=write_mode,
        **kwargs,
    )


async def _run(
    destination: PostgresDestination,
    target: TableTarget,
    *batches: pa.RecordBatch,
    batch_key: str | None = None,
    commit: bool = True,
) -> PreparedTarget:
    async with destination.connect():
        prepared = await destination.prepare(target)
        await destination.write(prepared, _batches(*batches), batch_key=batch_key)
        if commit:
            await destination.commit(prepared)
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


def _create_table(pg: psycopg.Connection, schema: str, table: str, ddl: str, comment: str | None = None) -> None:
    pg.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
    pg.execute(sql.SQL("CREATE TABLE {} ({})").format(sql.Identifier(schema, table), sql.SQL(ddl)))
    if comment is not None:
        pg.execute(sql.SQL("COMMENT ON TABLE {} IS {}").format(sql.Identifier(schema, table), sql.Literal(comment)))


@pytest.mark.parametrize(
    "write_mode, expected",
    [
        (WriteMode.APPEND, [(1, "a"), (2, "b"), (2, "B"), (3, "c")]),
        (WriteMode.MERGE, [(1, "a"), (2, "B"), (3, "c")]),
        (WriteMode.REPLACE, [(2, "B"), (3, "c")]),
    ],
)
async def test_write_modes_end_to_end(postgres_config, pg, schema, write_mode: WriteMode, expected: list) -> None:
    await _run(_destination(postgres_config), _target(schema, "events", write_mode), _rows((1, "a"), (2, "b")))
    second = _target(schema, "events", write_mode, staging_key="run2")
    prepared = await _run(_destination(postgres_config), second, _rows((2, "B")), _rows((3, "c")))

    assert _select(pg, schema, "events") == expected
    assert set(_columns(pg, schema, "events")) == {"id", "name"}
    assert prepared.existing_columns == ("id", "name")
    if write_mode != WriteMode.APPEND:
        assert not _exists(pg, schema, staging_table_name("events", "run2"))


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
    arrow_schema = pa.schema([("id", pa.int64()), ("value", arrow_type)])
    batch = pa.RecordBatch.from_pydict({"id": [1], "value": pa.array(values, type=arrow_type)}, schema=arrow_schema)

    with pytest.raises(ColumnTypeMappingError, match="'value'"):
        await _run(_destination(postgres_config), _target(schema, "t", WriteMode.APPEND, arrow_schema=arrow_schema))
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

    destination = _destination(postgres_config)

    async with destination.connect():
        with pytest.raises(PostgreSQLIncompatibleSchemaError, match="No matching columns"):
            await destination.prepare(_target(schema, "t", write_mode, new_columns=NewColumnPolicy.IGNORE))

    assert set(_columns(pg, schema, "t")) == {"other"}
    assert not _exists(pg, schema, staging_table_name("t", "run1"))


async def test_column_override_wins_over_the_type_policy(postgres_config, pg, schema) -> None:
    target = _target(schema, "t", WriteMode.APPEND, column_overrides={"name": "varchar(5)", "absent": "JSONB"})

    await _run(_destination(postgres_config), target, _rows((1, "abcde")))

    assert _columns(pg, schema, "t") == {"id": "bigint", "name": "character varying(5)"}
    assert _select(pg, schema, "t") == [(1, "abcde")]


@pytest.mark.parametrize(
    "target_kwargs, match",
    [
        ({"column_overrides": {"name": "TEXT; DROP TABLE t"}}, "not an allowed Postgres type"),
        ({"column_overrides": {"name": "INTEGER REFERENCES other"}}, "not an allowed Postgres type"),
        ({"column_overrides": {"absent": "TEXT DEFAULT now()"}}, "not an allowed Postgres type"),
        ({"namespace": ("another_database", "public")}, "is not the connected database"),
        ({"namespace": ("public",)}, r"must be \(database, schema\)"),
        ({"table_name": "x" * 64}, "longer than 63 bytes"),
        ({"arrow_schema": pa.schema([("id", pa.int64()), (BATCH_KEY_COLUMN, pa.string())])}, "reserved"),
    ],
)
async def test_invalid_target_is_rejected_before_any_table_exists(
    postgres_config, pg, schema, target_kwargs: dict, match: str
) -> None:
    target = _target(schema, "t", WriteMode.APPEND, **target_kwargs)

    with pytest.raises(PostgreSQLInvalidTargetError, match=match):
        destination = _destination(postgres_config)
        async with destination.connect():
            await destination.prepare(target)

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
    arrow_schema = pa.schema([("id", pa.int64()), ("version", pa.int64()), ("name", pa.string())])
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


@pytest.mark.parametrize(
    "version_keys, raises",
    [((), None), (("version",), MissingPrimaryKeyError)],
)
async def test_merge_into_a_table_without_a_unique_key(
    postgres_config, pg, schema, version_keys: tuple, raises: type[Exception] | None
) -> None:
    _create_table(pg, schema, "t", "id BIGINT, version BIGINT, name TEXT")
    pg.execute(sql.SQL("INSERT INTO {} VALUES (1, 1, 'a')").format(sql.Identifier(schema, "t")))
    arrow_schema = pa.schema([("id", pa.int64()), ("version", pa.int64()), ("name", pa.string())])
    batch = pa.RecordBatch.from_pylist([{"id": 1, "version": 2, "name": "b"}], schema=arrow_schema)
    target = _target(
        schema,
        "t",
        WriteMode.MERGE,
        arrow_schema=arrow_schema,
        merge=MergeSpec(primary_keys=("id",), version_keys=version_keys),
    )

    if raises is None:
        await _run(_destination(postgres_config), target, batch)
        await _run(_destination(postgres_config), target, batch)
        assert _select(pg, schema, "t", "id, version, name") == [(1, 2, "b")]
    else:
        with pytest.raises(raises):
            await _run(_destination(postgres_config), target, batch)


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
    arrow_schema = pa.schema([("id", pa.int64()), ("version", pa.int64()), ("name", pa.string())])
    target = _target(
        schema,
        "t",
        WriteMode.MERGE,
        arrow_schema=arrow_schema,
        merge=MergeSpec(primary_keys=("id",), version_keys=version_keys, dedupe_source=True),
    )
    destination = _destination(postgres_config)

    async with destination.connect():
        prepared = await destination.prepare(target)
        for index, (i, v, n) in enumerate(writes):
            batch = pa.RecordBatch.from_pylist([{"id": i, "version": v, "name": n}], schema=arrow_schema)
            await destination.write(prepared, _batches(batch), batch_key=str(index))
        await destination.commit(prepared)

    assert _select(pg, schema, "t", "id, version, name") == expected


async def test_duplicate_keys_without_dedupe_source_fail_the_merge(postgres_config, schema) -> None:
    with pytest.raises(psycopg.errors.CardinalityViolation):
        await _run(_destination(postgres_config), _target(schema, "t", WriteMode.MERGE), _rows((1, "a"), (1, "b")))


@pytest.mark.parametrize("write_mode", [WriteMode.MERGE, WriteMode.REPLACE])
async def test_retried_write_with_the_same_batch_key_does_not_duplicate(
    postgres_config, pg, schema, write_mode: WriteMode
) -> None:
    destination = _destination(postgres_config)

    async with destination.connect():
        prepared = await destination.prepare(_target(schema, "t", write_mode))
        await destination.write(prepared, _batches(_rows((1, "a"), (2, "b"))), batch_key="0")
        await destination.write(prepared, _batches(_rows((1, "a"), (2, "b"))), batch_key="0")
        await destination.write(prepared, _batches(_rows((3, "c"))), batch_key="1")

        assert pg.execute(
            sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(*prepared.write_into[1:]))
        ).fetchone() == (3,)
        await destination.commit(prepared)

    assert _select(pg, schema, "t") == [(1, "a"), (2, "b"), (3, "c")]
    assert BATCH_KEY_COLUMN not in _columns(pg, schema, "t")


async def test_append_refuses_a_batch_key(postgres_config, pg, schema) -> None:
    with pytest.raises(ValueError, match="batch key needs a staging table"):
        await _run(
            _destination(postgres_config), _target(schema, "t", WriteMode.APPEND), _rows((1, "a")), batch_key="0"
        )

    assert _select(pg, schema, "t") == []


@pytest.mark.parametrize("write_mode", [WriteMode.MERGE, WriteMode.REPLACE])
async def test_prepare_again_resumes_the_staging_table(postgres_config, pg, schema, write_mode: WriteMode) -> None:
    await _run(_destination(postgres_config), _target(schema, "t", write_mode), _rows((1, "a")), commit=False)

    resumed = await _run(_destination(postgres_config), _target(schema, "t", write_mode), _rows((2, "b")))

    assert _select(pg, schema, "t") == [(1, "a"), (2, "b")]
    assert not _exists(pg, schema, resumed.write_into[2])


async def test_resumed_merge_staging_gains_columns_added_to_the_final_table(postgres_config, pg, schema) -> None:
    await _run(_destination(postgres_config), _target(schema, "t", WriteMode.MERGE), _rows((1, "a")), commit=False)
    wider = pa.schema([*ROWS_SCHEMA, ("extra", pa.string())])
    batch = pa.RecordBatch.from_pylist([{"id": 2, "name": "b", "extra": "x"}], schema=wider)

    await _run(_destination(postgres_config), _target(schema, "t", WriteMode.MERGE, arrow_schema=wider), batch)

    assert _select(pg, schema, "t", "id, name, extra") == [(1, "a", None), (2, "b", "x")]


@pytest.mark.parametrize("write_mode", [WriteMode.APPEND, WriteMode.MERGE, WriteMode.REPLACE])
async def test_commit_twice_is_safe(postgres_config, pg, schema, write_mode: WriteMode) -> None:
    destination = _destination(postgres_config)

    async with destination.connect():
        prepared = await destination.prepare(_target(schema, "t", write_mode))
        await destination.write(prepared, _batches(_rows((1, "a"))))
        await destination.commit(prepared)
        await destination.commit(prepared)

    assert _select(pg, schema, "t") == [(1, "a")]


@pytest.mark.parametrize(
    "existing_comment, allowed",
    [
        (None, False),
        ("someone else", False),
        ("owner-tag123", False),
        ("owner-tag", True),
        ("owner-tag:published-by-run", True),
    ],
)
async def test_replace_refuses_a_table_without_the_owner_tag(
    postgres_config, pg, schema, existing_comment: str | None, allowed: bool
) -> None:
    _create_table(pg, schema, "t", "id BIGINT, name TEXT", comment=existing_comment)
    pg.execute(sql.SQL("INSERT INTO {} VALUES (0, 'old')").format(sql.Identifier(schema, "t")))
    target = _target(schema, "t", WriteMode.REPLACE, owner_tag="owner-tag")

    if allowed:
        await _run(_destination(postgres_config), target, _rows((1, "a")))
        assert _select(pg, schema, "t") == [(1, "a")]
        assert pg.execute("SELECT obj_description(%s::regclass)", (f'"{schema}"."t"',)).fetchone() == ("owner-tag",)
    else:
        with pytest.raises(PostgreSQLUnrelatedTableError):
            await _run(_destination(postgres_config), target, _rows((1, "a")))
        assert _select(pg, schema, "t") == [(0, "old")]


@pytest.mark.parametrize("write_mode", [WriteMode.APPEND, WriteMode.MERGE])
async def test_tables_this_destination_creates_carry_the_owner_tag(
    postgres_config, pg, schema, write_mode: WriteMode
) -> None:
    await _run(_destination(postgres_config), _target(schema, "t", write_mode, owner_tag="owner-tag"), _rows((1, "a")))

    assert pg.execute("SELECT obj_description(%s::regclass)", (f'"{schema}"."t"',)).fetchone() == ("owner-tag",)


@pytest.mark.parametrize("write_mode", [WriteMode.MERGE, WriteMode.REPLACE])
async def test_abort_drops_staging_and_keeps_the_final_table(
    postgres_config, pg, schema, write_mode: WriteMode
) -> None:
    await _run(_destination(postgres_config), _target(schema, "t", write_mode), _rows((1, "a")))
    destination = _destination(postgres_config)

    async with destination.connect():
        prepared = await destination.prepare(_target(schema, "t", write_mode, staging_key="run2"))
        await destination.write(prepared, _batches(_rows((2, "b"))))
        await destination.abort(prepared)

    await destination.abort(prepared)
    assert not _exists(pg, schema, prepared.write_into[2])
    assert _select(pg, schema, "t") == [(1, "a")]


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


async def test_json_and_text_values_round_trip(postgres_config, pg, schema) -> None:
    arrow_schema = pa.schema(
        [
            ("id", pa.int64()),
            ("properties", JsonType()),
            ("tags", pa.list_(pa.string())),
            ("text", pa.string()),
        ]
    )
    properties = {"nested": {"a": [1, 2]}, "quote": 'say "hi"', "tab": "a\tb", "null": "\u0000"}
    batch = pa.RecordBatch.from_arrays(
        [
            pa.array([1, 2]),
            pa.ExtensionArray.from_storage(JsonType(), pa.array([json.dumps(properties), None])),
            pa.array([["a", "{b}"], []], type=pa.list_(pa.string())),
            pa.array(['line\nbreak\t"quoted"', ""]),
        ],
        schema=arrow_schema,
    )

    await _run(_destination(postgres_config), _target(schema, "t", WriteMode.APPEND, arrow_schema=arrow_schema), batch)

    assert _columns(pg, schema, "t") == {"id": "bigint", "properties": "jsonb", "tags": "text[]", "text": "text"}
    assert _select(pg, schema, "t", "id, properties, tags, text") == [
        (1, {**properties, "null": ""}, ["a", "{b}"], 'line\nbreak\t"quoted"'),
        (2, None, [], ""),
    ]


async def test_probes_leave_the_connection_idle(postgres_config, schema) -> None:
    destination = _destination(postgres_config)

    async with destination.connect():
        await destination.prepare(_target(schema, "t", WriteMode.MERGE, owner_tag="owner-tag"))

        assert destination._require_client().connection.pgconn.transaction_status == psycopg.pq.TransactionStatus.IDLE


@pytest.mark.parametrize(
    "overrides",
    [
        {"credentials": {"password": "wrong"}},
        {"credentials": {"user": "no_such_role"}},
        {"config": {"database": "no_such_database"}},
        {"config": {"host": "no-such-host.invalid"}},
    ],
)
async def test_bad_connection_settings_are_configuration_errors(postgres_config, overrides: dict) -> None:
    with pytest.raises(PostgreSQLConnectionConfigurationError) as exc_info:
        async with _destination(postgres_config, **overrides).connect():
            pass

    assert isinstance(exc_info.value, DestinationConfigurationError)


@pytest.mark.parametrize(
    "overrides",
    [
        {"credentials": {"password": None}},
        {"config": {"host": None}},
        {"config": {"database": None}},
    ],
)
async def test_missing_inline_inputs_are_configuration_errors(postgres_config, overrides: dict) -> None:
    with pytest.raises(PostgreSQLMissingRequiredInputsError):
        async with _destination(postgres_config, **overrides).connect():
            pass


async def test_integration_credentials_win_over_inline_values(
    postgres_config, pg, schema, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def aget(team_id: int, integration_id: int) -> Integration:
        assert (team_id, integration_id) == (1, 42)
        return Integration(
            team_id=team_id,
            kind="postgresql",
            config={
                "host": postgres_config["host"],
                "port": postgres_config["port"],
                "user": postgres_config["user"],
                "ssl_mode": "prefer",
            },
            sensitive_config={"password": postgres_config["password"]},
        )

    monkeypatch.setattr(IntegrationManager.postgresql.credentials, "aget", aget)
    destination = _destination(postgres_config, integration_id=42, credentials={"password": "wrong"})

    await _run(destination, _target(schema, "t", WriteMode.APPEND), _rows((1, "a")))

    assert _select(pg, schema, "t") == [(1, "a")]


async def test_a_missing_integration_is_a_configuration_error(postgres_config, monkeypatch: pytest.MonkeyPatch) -> None:
    async def aget(team_id: int, integration_id: int) -> Integration:
        raise IntegrationNotFound("gone")

    monkeypatch.setattr(IntegrationManager.postgresql.credentials, "aget", aget)

    with pytest.raises(PostgreSQLIntegrationNotFoundError):
        async with _destination(postgres_config, integration_id=42).connect():
            pass


def test_the_facade_resolves_the_builtin_postgres_destination() -> None:
    destination = api.get_destination(DestinationConnection(destination_type="Postgres", team_id=1))

    assert isinstance(destination, PostgresDestination)
    assert "Postgres" in api.supported_destination_types()
