import io
import csv
import gzip
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from django.test import override_settings

import boto3
import pyarrow as pa
import structlog
import pyarrow.parquet as pq
from botocore.stub import Stubber
from deltalake import write_deltalake
from fsspec.implementations.local import LocalFileSystem
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store import formats
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    CsvOptions,
    DiscoveryOptions,
    ObjectStoreConfig,
    ObjectStoreProvider,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.delta import iter_delta_tables
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.discovery import (
    TableDefinition,
    group_tables,
    resolve_table_files,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    ACCESS_DENIED_ERROR,
    BLOCKED_LOCATION_ERROR,
    FILE_PARSE_ERROR,
    INVALID_CONFIG_ERROR,
    NO_SUCH_BUCKET_ERROR,
    NO_TABLE_FILES_ERROR,
    TOO_MANY_FILES_ERROR,
    WRONG_REGION_ERROR,
    ObjectStorageError,
    translate_storage_error,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem import (
    ObjectStore,
    S3ObjectStore,
    StoredObject,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.formats import (
    iter_csv_tables,
    iter_jsonl_tables,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.settings import MAX_TABLES
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.source_base import (
    iter_table,
    validate_store_location,
)

MODIFIED_AT = datetime(2024, 5, 1, 12, 0, tzinfo=UTC)
LOGGER = structlog.get_logger()


def stored(path: str) -> StoredObject:
    return StoredObject(path=path, size=10, modified_at=MODIFIED_AT)


def local_store(root: Path) -> ObjectStore:
    return ObjectStore(fs=LocalFileSystem(), root=str(root.resolve()), delta_uri_prefix="", delta_storage_options={})


def summarize(tables: list[TableDefinition]) -> list[tuple[str, str, str | None, str, str, list[str]]]:
    return [
        (table.name, table.kind, table.scope, table.path, table.file_format, [f.path for f in table.files])
        for table in tables
    ]


def read_rows(store: ObjectStore, table: TableDefinition) -> list[dict]:
    return [row for batch in iter_table(store, table, LOGGER) for row in batch.to_pylist()]


class TestGroupTables:
    @parameterized.expand(
        [
            (
                "delta_folder_is_one_table_and_hides_its_files",
                [
                    "sales/_delta_log/00000000000000000000.json",
                    "sales/part-0.parquet",
                    "events/a.csv",
                ],
                DiscoveryOptions(),
                [
                    ("sales", "delta", None, "sales", "delta", []),
                    ("events", "files", "folder", "events", "csv", ["events/a.csv"]),
                ],
            ),
            (
                "root_files_are_one_table_each",
                ["orders.csv.gz", "users.jsonl", "notes.txt"],
                DiscoveryOptions(),
                [
                    ("orders", "files", "file", "orders.csv.gz", "csv", ["orders.csv.gz"]),
                    ("users", "files", "file", "users.jsonl", "jsonl", ["users.jsonl"]),
                ],
            ),
            (
                "hive_partitions_fold_into_the_table_above",
                ["events/year=2024/month=01/a.parquet", "events/year=2024/month=02/b.parquet"],
                DiscoveryOptions(),
                [
                    (
                        "events",
                        "files",
                        "folder",
                        "events",
                        "parquet",
                        ["events/year=2024/month=01/a.parquet", "events/year=2024/month=02/b.parquet"],
                    ),
                ],
            ),
            (
                "hive_partitions_under_the_root_name_the_table_after_the_root",
                ["year=2024/a.parquet"],
                DiscoveryOptions(),
                [("exports", "files", "folder", "", "parquet", ["year=2024/a.parquet"])],
            ),
            (
                "combine_puts_every_file_in_one_table_and_keeps_delta_tables",
                ["a.csv", "daily/b.csv", "sales/_delta_log/0.json"],
                DiscoveryOptions(combined_table_name="All Orders"),
                [
                    ("sales", "delta", None, "sales", "delta", []),
                    ("all_orders", "files", "all", "", "csv", ["a.csv", "daily/b.csv"]),
                ],
            ),
            (
                "combine_with_mixed_formats_reads_each_file_by_extension",
                ["a.csv", "b.parquet"],
                DiscoveryOptions(combined_table_name="mixed"),
                [("mixed", "files", "all", "", "infer", ["a.csv", "b.parquet"])],
            ),
            (
                "delta_format_offers_only_delta_tables",
                ["a.csv", "sales/_delta_log/0.json", "sales/p.parquet"],
                DiscoveryOptions(file_format="delta"),
                [("sales", "delta", None, "sales", "delta", [])],
            ),
            (
                "explicit_format_reads_any_extension_and_skips_delta_tables",
                ["exports/a.txt", "exports/b", "sales/_delta_log/0.json", "sales/p.parquet"],
                DiscoveryOptions(file_format="csv_no_header"),
                [("exports", "files", "folder", "exports", "csv_no_header", ["exports/a.txt", "exports/b"])],
            ),
            (
                "spark_bookkeeping_files_are_skipped",
                ["out/_SUCCESS", "out/.part-0.crc", "out/_temporary/x.csv", "out/part-0.csv"],
                DiscoveryOptions(),
                [("out", "files", "folder", "out", "csv", ["out/part-0.csv"])],
            ),
            (
                "pattern_matches_across_folders",
                ["a/x.csv", "a/y.json", "b/z.csv"],
                DiscoveryOptions(file_pattern="*.csv"),
                [
                    ("a", "files", "folder", "a", "csv", ["a/x.csv"]),
                    ("b", "files", "folder", "b", "csv", ["b/z.csv"]),
                ],
            ),
            (
                "a_folder_with_two_formats_names_a_table_per_format",
                ["data/a.csv", "data/b.parquet"],
                DiscoveryOptions(),
                [
                    ("data_csv", "files", "folder", "data", "csv", ["data/a.csv"]),
                    ("data_parquet", "files", "folder", "data", "parquet", ["data/b.parquet"]),
                ],
            ),
            (
                "names_that_sanitize_alike_get_a_suffix",
                ["a-b.csv", "a_b.csv"],
                DiscoveryOptions(),
                [
                    ("a_b", "files", "file", "a-b.csv", "csv", ["a-b.csv"]),
                    ("a_b_2", "files", "file", "a_b.csv", "csv", ["a_b.csv"]),
                ],
            ),
        ]
    )
    def test_group_tables(
        self,
        _name: str,
        paths: list[str],
        options: DiscoveryOptions,
        expected: list[tuple[str, str, str | None, str, str, list[str]]],
    ) -> None:
        tables = group_tables([stored(path) for path in paths], options, root_name="exports")

        assert summarize(tables) == expected

    def test_metadata_round_trip_rebuilds_the_same_table(self) -> None:
        options = DiscoveryOptions(file_format="csv_no_header", file_pattern="*.txt", allow_double_quotes=False)
        [table] = group_tables([stored("exports/a.txt")], options, root_name="root")

        rebuilt = TableDefinition.from_schema_metadata(table.name, table.schema_metadata())

        assert rebuilt is not None
        assert rebuilt.same_location(table)
        assert (rebuilt.csv, rebuilt.pattern, rebuilt.source_format) == (
            CsvOptions(has_header=False, allow_double_quotes=False),
            "*.txt",
            "csv_no_header",
        )

    @parameterized.expand(
        [
            ("missing", None),
            ("unknown_kind", {"kind": "folder", "path": "a", "format": "csv"}),
            ("files_without_scope", {"kind": "files", "path": "a", "format": "csv"}),
            ("unknown_format", {"kind": "files", "scope": "folder", "path": "a", "format": "xml"}),
        ]
    )
    def test_unusable_metadata_falls_back_to_discovery(self, _name: str, metadata: dict | None) -> None:
        assert TableDefinition.from_schema_metadata("a", metadata) is None


class TestTableLimit:
    def test_names_that_sanitize_alike_get_increasing_suffixes(self) -> None:
        objects = [stored(f"{name}.csv") for name in ("a-b", "a_b", "a b", "a.b")]

        names = [table.name for table in group_tables(objects, DiscoveryOptions(), root_name="root")]

        assert sorted(names) == ["a_b", "a_b_2", "a_b_3", "a_b_4"]

    def test_an_unknown_file_format_is_an_invalid_config(self) -> None:
        with pytest.raises(ObjectStorageError, match=INVALID_CONFIG_ERROR):
            DiscoveryOptions(file_format="avro")  # type: ignore[arg-type]

    def test_discovery_stops_at_the_table_limit_but_resolving_a_table_does_not(self) -> None:
        objects = [stored(f"file_{index:05d}.csv") for index in range(MAX_TABLES + 1)]

        assert len(group_tables(objects, DiscoveryOptions(), root_name="root")) == MAX_TABLES
        assert len(group_tables(objects, DiscoveryOptions(), root_name="root", max_tables=None)) == MAX_TABLES + 1


class TestResolveTableFiles:
    def test_a_folder_table_leaves_out_subfolders_that_are_tables_of_their_own(self, tmp_path: Path) -> None:
        for path in ("events/a.csv", "events/year=2024/b.csv", "events/clicks/c.csv"):
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_text("id\n1\n")
        store = local_store(tmp_path)
        table = TableDefinition.from_schema_metadata(
            "events",
            {"kind": "files", "scope": "folder", "path": "events", "format": "csv", "source_format": "infer"},
        )
        assert table is not None

        resolved = resolve_table_files(store, table)

        assert [f.path for f in resolved.files] == ["events/a.csv", "events/year=2024/b.csv"]


@pytest.mark.parametrize(
    "paths, max_objects, expected",
    [
        (["t/a.csv", "t/b.csv", "t/c.csv"], 2, TOO_MANY_FILES_ERROR),
        (["other/a.csv"], 10, NO_TABLE_FILES_ERROR),
    ],
)
def test_sync_refuses_a_partial_or_missing_table(
    tmp_path: Path, paths: list[str], max_objects: int, expected: str
) -> None:
    for path in paths:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("id\n1\n")
    table = TableDefinition.from_schema_metadata(
        "t", {"kind": "files", "scope": "folder", "path": "t", "format": "csv", "source_format": "infer"}
    )
    assert table is not None

    with pytest.raises(ObjectStorageError, match=expected):
        resolve_table_files(local_store(tmp_path), table, max_objects=max_objects)


class TestCsv:
    @parameterized.expand(
        [
            (
                "header_with_quoted_delimiter",
                b'id,name\n1,"Smith, Jo"\n',
                CsvOptions(),
                [{"id": "1", "name": "Smith, Jo"}],
            ),
            (
                "no_header_uses_clickhouse_names",
                b"1,a\n2,b\n",
                CsvOptions(has_header=False),
                [
                    {"c1": "1", "c2": "a"},
                    {"c1": "2", "c2": "b"},
                ],
            ),
            (
                "double_quotes_off_keeps_quotes_as_text",
                b'id,name\n"1,2"\n',
                CsvOptions(allow_double_quotes=False),
                [{"id": '"1', "name": '2"'}],
            ),
            (
                "quoted_value_spans_lines",
                b'id,note\n1,"line one\nline two"\n',
                CsvOptions(),
                [{"id": "1", "note": "line one\nline two"}],
            ),
            (
                "empty_unquoted_is_null_and_empty_quoted_is_text",
                b'a,b\n,""\n',
                CsvOptions(),
                [{"a": None, "b": ""}],
            ),
            (
                "values_stay_text_when_later_rows_change_type",
                b"n\n1\nnot a number\n",
                CsvOptions(),
                [{"n": "1"}, {"n": "not a number"}],
            ),
            (
                "rows_with_the_wrong_field_count_are_skipped",
                b"a,b\n1,2\n1,2,3\n4,5\n",
                CsvOptions(),
                [{"a": "1", "b": "2"}, {"a": "4", "b": "5"}],
            ),
            (
                "byte_order_mark_and_duplicate_headers",
                b"\xef\xbb\xbfid,id,\n1,2,3\n",
                CsvOptions(),
                [{"id": "1", "id_2": "2", "c3": "3"}],
            ),
            ("empty_file", b"", CsvOptions(), []),
            (
                "headerless_quote_inside_an_unquoted_field_does_not_open_a_record",
                b'1,12" pipe,3\n4,5,6\n',
                CsvOptions(has_header=False),
                [{"c1": "1", "c2": '12" pipe', "c3": "3"}, {"c1": "4", "c2": "5", "c3": "6"}],
            ),
            (
                "repeated_headers_get_increasing_suffixes",
                b"a,a,a,a_2\n1,2,3,4\n",
                CsvOptions(),
                [{"a": "1", "a_2": "2", "a_3": "3", "a_2_2": "4"}],
            ),
            (
                "headerless_first_record_spans_lines",
                b'1,"line one\nline two",3\n4,5,6\n',
                CsvOptions(has_header=False),
                [{"c1": "1", "c2": "line one\nline two", "c3": "3"}, {"c1": "4", "c2": "5", "c3": "6"}],
            ),
        ]
    )
    def test_csv_rows(self, _name: str, content: bytes, options: CsvOptions, expected: list[dict]) -> None:
        rows = [row for table in iter_csv_tables(io.BytesIO(content), options) for row in table.to_pylist()]

        assert rows == expected

    def test_an_unterminated_quote_in_the_first_record_stays_within_the_record_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(formats, "MAX_FIRST_CSV_RECORD_BYTES", 64)
        content = b'1,"open\n' + b"line\n" * 100

        with pytest.raises(ObjectStorageError, match=FILE_PARSE_ERROR):
            list(iter_csv_tables(io.BytesIO(content), CsvOptions(has_header=False), file_path="x.csv"))

    def test_a_header_only_file_is_a_table_with_no_rows(self) -> None:
        tables = list(iter_csv_tables(io.BytesIO(b"id,name\n"), CsvOptions()))

        assert [(table.column_names, table.num_rows) for table in tables] == [(["id", "name"], 0)]

    def test_an_oversized_first_row_field_is_a_parse_error(self) -> None:
        # Other code in the process may have raised the csv module's global field limit.
        previous_limit = csv.field_size_limit(1024)
        try:
            with pytest.raises(ObjectStorageError, match=FILE_PARSE_ERROR):
                content = io.BytesIO(b"a," + b"x" * 2048 + b"\n")
                list(iter_csv_tables(content, CsvOptions(has_header=False), file_path="big.csv"))
        finally:
            csv.field_size_limit(previous_limit)


class TestJsonl:
    def test_chunks_by_row_count_and_wraps_scalars(self) -> None:
        content = b'{"id": 1}\n\n{"id": 2}\n[{"id": 3}, 4]\n"five"\n'

        tables = list(iter_jsonl_tables(io.BytesIO(content), max_rows=2))

        assert [table.num_rows for table in tables] == [2, 2, 1]
        assert [row for table in tables for row in table.to_pylist()] == [
            {"id": 1},
            {"id": 2},
            {"id": 3, "value": None},
            {"id": None, "value": 4},
            {"value": "five"},
        ]

    def test_a_too_deeply_nested_record_is_a_parse_error(self) -> None:
        with pytest.raises(ObjectStorageError, match=FILE_PARSE_ERROR):
            list(iter_jsonl_tables(io.BytesIO(b"[" * 100_000 + b"]" * 100_000 + b"\n"), "deep.jsonl"))

    def test_invalid_line_names_the_file_and_line(self) -> None:
        with pytest.raises(ObjectStorageError, match=f"{FILE_PARSE_ERROR} 'x.jsonl' as JSON Lines: line 2"):
            list(iter_jsonl_tables(io.BytesIO(b'{"id": 1}\n{oops\n'), "x.jsonl"))

    def test_a_line_over_the_record_limit_is_a_parse_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(formats, "MAX_RECORD_BYTES", 16)

        with pytest.raises(ObjectStorageError, match=f"{FILE_PARSE_ERROR} 'x.jsonl' as JSON Lines"):
            list(iter_jsonl_tables(io.BytesIO(b'{"id": 1}\n{"id": "' + b"x" * 64 + b'"}\n'), "x.jsonl"))


class TestReadTable:
    def test_reads_each_format_and_tags_rows_with_their_file(self, tmp_path: Path) -> None:
        (tmp_path / "mixed").mkdir()
        (tmp_path / "mixed" / "a.csv.gz").write_bytes(gzip.compress(b"id\n1\n"))
        (tmp_path / "mixed" / "b.jsonl").write_bytes(b'{"id": "2"}\n')
        pq.write_table(pa.table({"id": ["3"]}), tmp_path / "mixed" / "c.parquet")
        store = local_store(tmp_path)
        [table] = group_tables(
            store.list_objects("", 100), DiscoveryOptions(combined_table_name="mixed"), root_name="root"
        )

        rows = read_rows(store, table)

        assert [(row["id"], row["_file_name"]) for row in rows] == [
            ("1", "mixed/a.csv.gz"),
            ("2", "mixed/b.jsonl"),
            ("3", "mixed/c.parquet"),
        ]
        assert all(row["_file_modified_at"].tzinfo is not None for row in rows)

    def test_gzipped_parquet_is_unpacked_before_it_is_read(self, tmp_path: Path) -> None:
        buffer = io.BytesIO()
        pq.write_table(pa.table({"id": ["1", "2"]}), buffer)
        (tmp_path / "orders.parquet.gz").write_bytes(gzip.compress(buffer.getvalue()))
        store = local_store(tmp_path)
        [table] = group_tables(store.list_objects("", 10), DiscoveryOptions(), root_name="root")

        assert [row["id"] for row in read_rows(store, table)] == ["1", "2"]

    def test_gzipped_parquet_over_the_unpacked_size_limit_is_a_parse_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(formats, "MAX_UNPACKED_PARQUET_BYTES", 16)
        (tmp_path / "big.parquet.gz").write_bytes(gzip.compress(b"x" * 1024))
        store = local_store(tmp_path)
        [table] = group_tables(store.list_objects("", 10), DiscoveryOptions(), root_name="root")

        with pytest.raises(ObjectStorageError, match=FILE_PARSE_ERROR):
            read_rows(store, table)

    def test_a_parquet_file_with_no_rows_still_yields_its_schema(self, tmp_path: Path) -> None:
        pq.write_table(pa.table({"id": pa.array([], pa.string())}), tmp_path / "empty.parquet")
        store = local_store(tmp_path)
        [table] = group_tables(store.list_objects("", 10), DiscoveryOptions(), root_name="root")

        batches = list(iter_table(store, table, LOGGER))

        assert [(batch.column_names[0], batch.num_rows) for batch in batches] == [("id", 0)]

    def test_corrupt_gzip_is_a_parse_error(self, tmp_path: Path) -> None:
        (tmp_path / "bad.csv.gz").write_bytes(b"not gzip")
        store = local_store(tmp_path)
        [table] = group_tables(store.list_objects("", 10), DiscoveryOptions(), root_name="root")

        with pytest.raises(ObjectStorageError, match=FILE_PARSE_ERROR):
            read_rows(store, table)

    def test_delta_read_stays_on_the_version_it_opened(self, tmp_path: Path) -> None:
        table_path = tmp_path / "sales"
        write_deltalake(str(table_path), pa.table({"id": [1]}))
        write_deltalake(str(table_path), pa.table({"id": [2]}), mode="append")
        store = local_store(tmp_path)
        [table] = group_tables(store.list_objects("", 100), DiscoveryOptions(), root_name="root")
        assert table.kind == "delta"

        batches = iter_delta_tables(store.delta_uri(table.path), {}, table.name, batch_rows=1)
        first = next(batches)
        write_deltalake(str(table_path), pa.table({"id": [7, 8, 9]}), mode="overwrite")
        rest = list(batches)

        assert sorted(row["id"] for batch in [first, *rest] for row in batch.to_pylist()) == [1, 2]

    def test_an_empty_delta_snapshot_still_yields_its_schema(self, tmp_path: Path) -> None:
        table_path = tmp_path / "sales"
        write_deltalake(str(table_path), pa.table({"id": [1]}))
        write_deltalake(str(table_path), pa.table({"id": pa.array([], pa.int64())}), mode="overwrite")
        store = local_store(tmp_path)

        tables = list(iter_delta_tables(store.delta_uri("sales"), {}, "sales"))

        assert [(table.column_names, table.num_rows) for table in tables] == [(["id"], 0)]


class TestLocationAndErrors:
    @parameterized.expand(
        [
            ("bucket_with_a_host", {"bucket": "evil.com/x"}, INVALID_CONFIG_ERROR),
            ("bucket_with_a_scheme", {"bucket": "s3://data"}, INVALID_CONFIG_ERROR),
            ("region_with_a_host", {"region": "us-east-1.evil.com"}, INVALID_CONFIG_ERROR),
            ("missing_secret", {"secret_access_key": " "}, INVALID_CONFIG_ERROR),
            ("parent_folder", {"prefix": "a/../b"}, INVALID_CONFIG_ERROR),
        ]
    )
    def test_config_rejects_values_that_could_retarget_the_request(
        self, _name: str, overrides: dict, expected: str
    ) -> None:
        values = {
            "provider": ObjectStoreProvider.S3,
            "bucket": "customer-data",
            "region": "us-east-1",
            "access_key_id": "AKIAEXAMPLE",
            "secret_access_key": "secret",
            **overrides,
        }

        with pytest.raises(ObjectStorageError, match=expected):
            ObjectStoreConfig(**values)

    def test_posthog_owned_bucket_is_blocked(self) -> None:
        config = ObjectStoreConfig(
            provider=ObjectStoreProvider.S3,
            bucket="posthog-owned",
            region="us-east-1",
            access_key_id="AKIAEXAMPLE",
            secret_access_key="secret",
        )

        with override_settings(DATAWAREHOUSE_BUCKET="posthog-owned"):
            with pytest.raises(ObjectStorageError, match=BLOCKED_LOCATION_ERROR):
                validate_store_location(config)

    @parameterized.expand(
        [
            ("access_denied", PermissionError("Access Denied"), ACCESS_DENIED_ERROR),
            ("no_such_bucket", FileNotFoundError("The specified bucket does not exist"), NO_SUCH_BUCKET_ERROR),
            (
                "wrong_region",
                OSError("An error occurred (PermanentRedirect) when calling the ListObjectsV2 operation"),
                WRONG_REGION_ERROR,
            ),
        ]
    )
    def test_storage_errors_map_to_stable_prefixes(self, _name: str, error: Exception, expected: str) -> None:
        assert str(translate_storage_error(error, "customer-data")).startswith(expected)

    def test_unknown_storage_errors_stay_retryable(self) -> None:
        error = ConnectionResetError("reset by peer")

        assert translate_storage_error(error, "customer-data") is error


def _s3_store(client: Any) -> S3ObjectStore:
    return S3ObjectStore(
        fs=LocalFileSystem(),
        root="customer-data/exports",
        delta_uri_prefix="s3://",
        delta_storage_options={},
        client=client,
        bucket="customer-data",
        prefix="exports",
    )


def _listing(*keys: str, next_token: str | None = None) -> dict[str, Any]:
    response: dict[str, Any] = {
        "Contents": [{"Key": key, "Size": 5, "LastModified": MODIFIED_AT} for key in keys],
        "IsTruncated": next_token is not None,
    }
    if next_token is not None:
        response["NextContinuationToken"] = next_token
    return response


class TestS3Listing:
    @parameterized.expand(
        [
            (
                "pages_until_the_cap",
                "",
                3,
                [
                    ({"Prefix": "exports/"}, _listing("exports/a.csv", "exports/dir/", next_token="t1")),
                    (
                        {"Prefix": "exports/", "ContinuationToken": "t1"},
                        _listing("exports/b.csv", "exports/c.csv", "exports/d.csv"),
                    ),
                ],
                ["a.csv", "b.csv", "c.csv"],
            ),
            (
                "a_prefix_that_names_one_file",
                "orders.csv",
                10,
                [
                    ({"Prefix": "exports/orders.csv/"}, _listing()),
                    ({"Prefix": "exports/orders.csv", "MaxKeys": 1000}, _listing("exports/orders.csv")),
                ],
                ["orders.csv"],
            ),
        ]
    )
    def test_list_objects(
        self,
        _name: str,
        relative_prefix: str,
        max_objects: int,
        pages: list[tuple[dict[str, Any], dict[str, Any]]],
        expected: list[str],
    ) -> None:
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="secret"
        )
        with Stubber(client) as stubber:
            for params, response in pages:
                stubber.add_response(
                    "list_objects_v2", response, {"Bucket": "customer-data", "MaxKeys": 1000, **params}
                )

            listed = _s3_store(client).list_objects(relative_prefix, max_objects)

        assert [stored.path for stored in listed] == expected

    def test_rejected_credentials_become_an_access_error(self) -> None:
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="secret"
        )
        with Stubber(client) as stubber:
            stubber.add_client_error("list_objects_v2", service_error_code="InvalidAccessKeyId", http_status_code=403)

            with pytest.raises(PermissionError):
                _s3_store(client).list_objects("", 10)
