import io
import decimal
import datetime as dt
import threading

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from products.managed_warehouse.backend.temporal import ducklake_register_trino as trino_registration
from products.managed_warehouse.backend.temporal.ducklake_register_trino import (
    ParquetFooter,
    StagingColumn,
    TrinoRegistrationCatalog,
    add_files_batches,
    read_parquet_footers,
    staging_table_name,
    staging_table_schema,
    stale_staging_tables,
    trino_type_for_arrow,
)


class _FakeFilesystem:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def open(self, path: str, mode: str = "rb") -> io.BytesIO:
        return io.BytesIO(self.files[path])


def _parquet_bytes(table: pa.Table) -> bytes:
    sink = io.BytesIO()
    pq.write_table(table, sink)
    return sink.getvalue()


def _footer(path: str, **types: pa.DataType) -> ParquetFooter:
    return ParquetFooter(path=path, num_rows=1, schema=pa.schema(list(types.items())))


@parameterized.expand(
    [
        ("utf8", pa.string(), "VARCHAR"),
        ("large_utf8", pa.large_string(), "VARCHAR"),
        ("int64", pa.int64(), "BIGINT"),
        ("int32", pa.int32(), "INTEGER"),
        ("int16", pa.int16(), "SMALLINT"),
        ("int8", pa.int8(), "TINYINT"),
        ("float64", pa.float64(), "DOUBLE"),
        ("float32", pa.float32(), "REAL"),
        ("bool", pa.bool_(), "BOOLEAN"),
        ("date32", pa.date32(), "DATE"),
        ("timestamp_us", pa.timestamp("us"), "TIMESTAMP(6)"),
        ("timestamp_us_tz", pa.timestamp("us", tz="UTC"), "TIMESTAMP(6) WITH TIME ZONE"),
        ("timestamp_us_named_tz", pa.timestamp("us", tz="America/New_York"), "TIMESTAMP(6) WITH TIME ZONE"),
        ("decimal", pa.decimal128(10, 2), "DECIMAL(10, 2)"),
        ("decimal_max", pa.decimal128(38, 18), "DECIMAL(38, 18)"),
        ("binary", pa.binary(), "VARBINARY"),
        ("large_binary", pa.large_binary(), "VARBINARY"),
        ("timestamp_ns", pa.timestamp("ns"), None),
        ("timestamp_ms", pa.timestamp("ms"), None),
        ("time", pa.time64("us"), None),
        ("duration", pa.duration("us"), None),
        ("date64", pa.date64(), None),
        ("uint32", pa.uint32(), None),
        ("null", pa.null(), None),
        ("decimal256", pa.decimal256(40, 2), None),
        ("list", pa.list_(pa.int64()), None),
        ("struct", pa.struct([("a", pa.int64())]), None),
        ("dictionary", pa.dictionary(pa.int32(), pa.string()), None),
    ]
)
def test_trino_type_for_arrow(_name: str, arrow_type: pa.DataType, expected: str | None) -> None:
    assert trino_type_for_arrow(arrow_type) == expected


def test_staging_schema_unions_file_columns_and_appends_hive_partitions() -> None:
    schema = staging_table_schema(
        [
            _footer("a.parquet", id=pa.int64(), name=pa.string()),
            _footer("b.parquet", id=pa.int64(), created_at=pa.timestamp("us")),
        ],
        ["_ph_partition_key"],
    )

    assert schema.columns == (
        StagingColumn(name="id", trino_type="BIGINT"),
        StagingColumn(name="name", trino_type="VARCHAR"),
        StagingColumn(name="created_at", trino_type="TIMESTAMP(6)"),
        StagingColumn(name="_ph_partition_key", trino_type="VARCHAR"),
    )
    assert schema.partition_columns == ("_ph_partition_key",)


@parameterized.expand(
    [
        ("unsupported_type", [_footer("a.parquet", at=pa.time64("us"))], [], "unsupported type"),
        (
            "conflicting_types",
            [_footer("a.parquet", id=pa.int32()), _footer("b.parquet", id=pa.int64())],
            [],
            "INTEGER in one file and BIGINT",
        ),
        (
            "case_folded_names",
            [_footer("a.parquet", id=pa.int64()), _footer("b.parquet", ID=pa.int64())],
            [],
            "differ only in case",
        ),
        ("partition_in_file", [_footer("a.parquet", key=pa.string())], ["Key"], "collides with column 'key'"),
        ("partition_name", [_footer("a.parquet", id=pa.int64())], ["day(key)"], "not a plain identifier"),
    ]
)
def test_staging_schema_rejects_files_it_cannot_register(
    _name: str, footers: list[ParquetFooter], hive_columns: list[str], message: str
) -> None:
    with pytest.raises(ApplicationError, match=message) as error:
        staging_table_schema(footers, hive_columns)

    assert error.value.non_retryable is True


def test_read_parquet_footers_reads_row_counts_and_types_from_the_files() -> None:
    first = pa.table(
        {
            "id": pa.array([1, 2, 3], pa.int64()),
            "amount": pa.array([decimal.Decimal("1.50")] * 3, pa.decimal128(10, 2)),
            "at": pa.array([dt.datetime(2026, 1, 1, tzinfo=dt.UTC)] * 3, pa.timestamp("us", tz="UTC")),
        }
    )
    second = pa.table({"id": pa.array([4], pa.int64()), "note": pa.array(["x"], pa.large_string())})
    filesystem = _FakeFilesystem(
        {"s3://bucket/a.parquet": _parquet_bytes(first), "s3://bucket/b.parquet": _parquet_bytes(second)}
    )

    footers = read_parquet_footers(filesystem, ["s3://bucket/a.parquet", "s3://bucket/b.parquet"])

    assert [(footer.path, footer.num_rows) for footer in footers] == [
        ("s3://bucket/a.parquet", 3),
        ("s3://bucket/b.parquet", 1),
    ]
    assert staging_table_schema(footers, []).columns == (
        StagingColumn(name="id", trino_type="BIGINT"),
        StagingColumn(name="amount", trino_type="DECIMAL(10, 2)"),
        StagingColumn(name="at", trino_type="TIMESTAMP(6) WITH TIME ZONE"),
        StagingColumn(name="note", trino_type="VARCHAR"),
    )


@parameterized.expand(
    [
        ("count_limit", 4001, 10_000_000, [2000, 2000, 1]),
        ("character_limit", 10, 3 * len("'s3://bucket/file-0000.parquet', "), [3, 3, 3, 1]),
    ]
)
def test_add_files_batches_bound_files_and_statement_size(
    _name: str, file_count: int, max_characters: int, expected_sizes: list[int]
) -> None:
    paths = [f"s3://bucket/file-{index:04d}.parquet" for index in range(file_count)]

    batches = add_files_batches(paths, max_characters=max_characters)

    assert [len(batch) for batch in batches] == expected_sizes
    assert [path for batch in batches for path in batch] == paths


def _catalog() -> tuple[TrinoRegistrationCatalog, MagicMock]:
    connection = MagicMock(catalog='tenant_"catalog')
    cursor = connection.cursor.return_value
    cursor.fetchall.return_value = [["added_data_files", 1]]
    return TrinoRegistrationCatalog(connection), cursor


def _executed(cursor: MagicMock) -> list[str]:
    return [call.args[0] for call in cursor.execute.call_args_list]


def test_register_files_batches_add_files_with_stable_import_ids() -> None:
    catalog, cursor = _catalog()
    paths = [f"s3://bucket/_imports/s/t/file-{index:04d}.parquet" for index in range(4001)]

    catalog.register_files("imports", "__ph_register_x", paths, generation_token="1234567890_abcdef12")

    statements = _executed(cursor)
    assert len(statements) == 3
    for index, statement in enumerate(statements):
        assert statement.startswith('ALTER TABLE "tenant_""catalog"."imports"."__ph_register_x" EXECUTE add_files(')
        assert f"import_id => '1234567890_abcdef12-b{index}'" in statement
        assert statement.endswith("allow_missing => true, hive_partitioning => true)")
    assert "'s3://bucket/_imports/s/t/file-0000.parquet'" in statements[0]
    assert "'s3://bucket/_imports/s/t/file-4000.parquet'" in statements[2]
    assert statements[2].count("s3://") == 1


def test_catalog_statements_quote_identifiers_and_literals() -> None:
    catalog, cursor = _catalog()
    schema = staging_table_schema([_footer("a.parquet", **{'we"ird': pa.int64()})], ["_ph_partition_key"])
    cursor.fetchall.side_effect = [[], [], [[7]], [["replaced_tables", 1]], []]

    catalog.create_schema("imports")
    catalog.create_staging_table("imports", "__ph_register_x", schema)
    assert catalog.count_rows("imports", "__ph_register_x") == 7
    assert catalog.publish_as("imports", "__ph_register_x", target="it's_live") == 1
    catalog.drop_table("imports", "__ph_register_x")

    assert _executed(cursor) == [
        'CREATE SCHEMA IF NOT EXISTS "tenant_""catalog"."imports"',
        'CREATE TABLE "tenant_""catalog"."imports"."__ph_register_x" '
        '("we""ird" BIGINT, "_ph_partition_key" VARCHAR) '
        "WITH (partitioning = ARRAY['_ph_partition_key'])",
        'SELECT count(*) FROM "tenant_""catalog"."imports"."__ph_register_x"',
        'ALTER TABLE "tenant_""catalog"."imports"."__ph_register_x" EXECUTE publish_as(target => \'it\'\'s_live\')',
        'DROP TABLE IF EXISTS "tenant_""catalog"."imports"."__ph_register_x"',
    ]


def test_stale_staging_tables_keeps_young_and_foreign_tables() -> None:
    now = dt.datetime.now(dt.UTC)
    old = staging_table_name(now - dt.timedelta(hours=7), "0" * 16)
    older = staging_table_name(now - dt.timedelta(days=3), "1" * 16)
    young = staging_table_name(now - dt.timedelta(hours=1), "2" * 16)
    duckgres_shadow = f"__ph_register_{'3' * 32}"

    stale = stale_staging_tables(
        [young, old, "postgres_customers", duckgres_shadow, older],
        now=now,
        min_age=dt.timedelta(hours=6),
        limit=15,
    )

    assert stale == [old, older]
    assert stale_staging_tables([old, older], now=now, min_age=dt.timedelta(hours=6), limit=1) == [old]


def test_catalog_cancels_a_running_statement_at_the_deadline() -> None:
    connection = MagicMock(catalog="tenant")
    cursor = connection.cursor.return_value
    cancelled = threading.Event()
    cursor.cancel.side_effect = cancelled.set

    def execute(_statement: str) -> None:
        cancelled.wait(timeout=5)
        raise RuntimeError("Query was canceled")

    cursor.execute.side_effect = execute
    with (
        patch.object(trino_registration, "connect_managed_warehouse_trino") as connect,
        pytest.raises(RuntimeError, match="canceled"),
    ):
        connect.return_value.__enter__.return_value = connection
        with TrinoRegistrationCatalog.connect("org", principal="principal", cancel_after_seconds=0.2) as catalog:
            catalog.count_rows("imports", "__ph_register_x")

    connect.assert_called_once_with("org", principal="principal")
    cursor.cancel.assert_called()
