import io
import os
import csv
import gzip
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from django.test import override_settings

import boto3
import pyarrow as pa
import structlog
import pyarrow.parquet as pq
from botocore.stub import Stubber
from deltalake import DeltaTable, WriterProperties, write_deltalake
from fsspec.implementations.local import LocalFileSystem
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store import (
    delta,
    formats,
    source_base,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    CsvOptions,
    DiscoveryOptions,
    ObjectStoreConfig,
    ObjectStoreProvider,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.delta import (
    ObjectStorageDeltaCursor,
    iter_delta_tables,
    plan_delta_read,
)
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
    iter_file_tables,
    iter_jsonl_tables,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.incremental import (
    FileSelection,
    listing_digest,
    plan_mirror,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.settings import (
    JSONL_CHUNK_ROWS,
    MAX_TABLES,
    PARQUET_BATCH_ROWS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.source_base import (
    iter_table,
    validate_store_location,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import ReplaceScope

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
                "a_hive_partition_folder_whose_key_starts_with_an_underscore_holds_data",
                ["orders/_ph_partition_key=2024-w10/part.parquet", "orders/_ph_partition_key=2024-w11/part.parquet"],
                DiscoveryOptions(),
                [
                    (
                        "orders",
                        "files",
                        "folder",
                        "orders",
                        "parquet",
                        [
                            "orders/_ph_partition_key=2024-w10/part.parquet",
                            "orders/_ph_partition_key=2024-w11/part.parquet",
                        ],
                    ),
                ],
            ),
            (
                "nested_underscore_hive_partitions_fold_into_the_table_above",
                ["orders/_a=1/_b=2/part.parquet", "orders/_a=1/_b=3/part.parquet"],
                DiscoveryOptions(),
                [
                    (
                        "orders",
                        "files",
                        "folder",
                        "orders",
                        "parquet",
                        ["orders/_a=1/_b=2/part.parquet", "orders/_a=1/_b=3/part.parquet"],
                    ),
                ],
            ),
            (
                "bookkeeping_stays_skipped_inside_an_underscore_partition",
                [
                    "orders/_ph_partition_key=2024-w10/_SUCCESS",
                    "orders/_ph_partition_key=2024-w10/_committed_123",
                    "orders/_ph_partition_key=2024-w10/.part.parquet.crc",
                    "orders/_ph_partition_key=2024-w10/_temporary/x.parquet",
                    "orders/_temporary/_a=1/x.parquet",
                    "orders/.hidden=1/x.parquet",
                    "orders/_ph_partition_key=2024-w10/part.parquet",
                ],
                DiscoveryOptions(),
                [
                    (
                        "orders",
                        "files",
                        "folder",
                        "orders",
                        "parquet",
                        ["orders/_ph_partition_key=2024-w10/part.parquet"],
                    ),
                ],
            ),
            (
                "a_delta_table_under_an_underscore_partition_folder_is_found",
                ["_region=eu/sales/_delta_log/0.json", "_temporary/sales/_delta_log/0.json"],
                DiscoveryOptions(),
                [("region_eu_sales", "delta", None, "_region=eu/sales", "delta", [])],
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

    @parameterized.expand(
        [
            (
                "star_stays_in_its_folder",
                ["a.csv", "daily/b.csv"],
                "*.csv",
                "",
                DiscoveryOptions(),
                [("a", "files", "file", "a.csv", "csv", ["a.csv"])],
            ),
            (
                "double_star_crosses_folders",
                ["a.csv", "daily/b.csv", "daily/c.json"],
                "**.csv",
                "",
                DiscoveryOptions(),
                [
                    ("a", "files", "file", "a.csv", "csv", ["a.csv"]),
                    ("daily", "files", "folder", "daily", "csv", ["daily/b.csv"]),
                ],
            ),
            (
                "underscore_hive_partitions_under_the_root_make_one_table",
                [
                    "_part_key=2024-w10/part-0.parquet",
                    "_part_key=2024-w11/part-0.parquet",
                    "_part_key=2024-w11/_SUCCESS",
                    "notes.txt",
                ],
                "**/*.parquet",
                "",
                DiscoveryOptions(),
                [
                    (
                        "orders",
                        "files",
                        "folder",
                        "",
                        "parquet",
                        ["_part_key=2024-w10/part-0.parquet", "_part_key=2024-w11/part-0.parquet"],
                    )
                ],
            ),
            (
                "a_delta_table_needs_the_pattern_to_match_one_of_its_files",
                ["sales/_delta_log/0.json", "sales/p.parquet", "refunds/_delta_log/0.json", "a.csv"],
                "**.parquet",
                "",
                DiscoveryOptions(),
                [("sales", "delta", None, "sales", "delta", [])],
            ),
        ]
    )
    def test_url_selection(
        self,
        _name: str,
        paths: list[str],
        pattern: str | None,
        listing_prefix: str,
        options: DiscoveryOptions,
        expected: list[tuple[str, str, str | None, str, str, list[str]]],
    ) -> None:
        tables = group_tables(
            [stored(path) for path in paths],
            options,
            root_name="orders",
            pattern=pattern,
            listing_prefix=listing_prefix,
        )

        assert summarize(tables) == expected

    def test_a_combined_table_lists_only_its_listing_prefix_at_sync(self, tmp_path: Path) -> None:
        for path in ("daily/a.csv", "daily/2024/b.csv", "daily-archive/c.csv", "other.csv"):
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_text("id\n1\n")
        [table] = group_tables(
            [stored("daily/a.csv")],
            DiscoveryOptions(combined_table_name="daily"),
            root_name="r",
            listing_prefix="daily",
        )

        resolved = resolve_table_files(local_store(tmp_path), table)

        assert [f.path for f in resolved.files] == ["daily/2024/b.csv", "daily/a.csv"]

    def test_metadata_round_trip_rebuilds_the_same_table(self) -> None:
        options = DiscoveryOptions(file_format="csv_no_header", allow_double_quotes=False)
        [table] = group_tables([stored("exports/a.txt")], options, root_name="root", pattern="**.txt")

        rebuilt = TableDefinition.from_schema_metadata(table.name, table.schema_metadata())

        assert rebuilt is not None
        assert rebuilt.same_location(table)
        assert (rebuilt.csv, rebuilt.pattern, rebuilt.source_format) == (
            CsvOptions(has_header=False, allow_double_quotes=False),
            "**.txt",
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
    def test_a_line_holding_a_large_array_is_chunked_by_row_count(self) -> None:
        tables = list(iter_jsonl_tables(io.BytesIO(b"[" + b",".join(b"1" for _ in range(25)) + b"]\n"), max_rows=10))

        assert [table.num_rows for table in tables] == [10, 10, 5]

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

    @parameterized.expand([("plain", "orders.parquet", False), ("gzipped", "orders.parquet.gz", True)])
    def test_a_parquet_file_with_one_brotli_column_is_a_parse_error(self, _name: str, path: str, gzipped: bool) -> None:
        buffer = io.BytesIO()
        pq.write_table(
            pa.table({"id": ["1", "2"], "note": ["a", "b"]}),
            buffer,
            compression={"id": "snappy", "note": "brotli"},
        )
        content = gzip.compress(buffer.getvalue()) if gzipped else buffer.getvalue()

        with pytest.raises(ObjectStorageError, match=f"{FILE_PARSE_ERROR} '{path}' as Parquet: Brotli"):
            list(iter_file_tables(io.BytesIO(content), stored(path), "parquet", CsvOptions()))

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

    @parameterized.expand([("whole_snapshot", False), ("by_file", True)])
    def test_a_delta_table_with_brotli_compression_is_a_parse_error(self, _name: str, with_file_names: bool) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "sales")
            write_deltalake(path, pa.table({"id": [1, 2]}), writer_properties=WriterProperties(compression="BROTLI"))

            read = plan_delta_read(path, {}, "sales")

            with pytest.raises(ObjectStorageError, match=f"{FILE_PARSE_ERROR} '.+' in the Delta table 'sales': Brotli"):
                list(read.iter_tables(with_file_names=with_file_names))


def _append(path: str) -> None:
    write_deltalake(path, pa.table({"id": [3], "day": ["b"]}), mode="append")


def _overwrite(path: str) -> None:
    write_deltalake(path, pa.table({"id": [9], "day": ["c"]}), mode="overwrite")


def _delete(path: str) -> None:
    DeltaTable(path).delete("id = 1")


def _append_then_compact(path: str) -> None:
    _append(path)
    DeltaTable(path).optimize.compact()


def _update(path: str) -> None:
    DeltaTable(path).update(updates={"id": "10"}, predicate="id = 2")


def _merge(path: str) -> None:
    (
        DeltaTable(path)
        .merge(pa.table({"id": [2, 4], "day": ["b", "c"]}), predicate="t.id = s.id", source_alias="s", target_alias="t")
        .when_matched_update(updates={"id": "s.id + 20"})
        .when_not_matched_insert_all()
        .execute()
    )


def _files_and_ids(path: str, version: int | None = None) -> list[tuple[str, int]]:
    dataset = DeltaTable(path, version=version).to_pyarrow_dataset()
    return sorted(
        (fragment.path, row_id)
        for fragment in dataset.get_fragments()
        for row_id in fragment.to_table(columns=["id"]).column("id").to_pylist()
    )


class TestDeltaCursor:
    @parameterized.expand(
        [
            ("no_cursor_reads_the_snapshot", None, [_append], False, False, [1, 2, 3], 1),
            ("appends_read_only_the_new_files", "same", [_append], False, False, [3], 1),
            ("an_unchanged_table_reads_nothing", "same", [], False, False, [], 0),
            ("an_overwrite_rebuilds", "same", [_overwrite], False, True, [9], 1),
            ("a_delete_rebuilds", "same", [_delete], False, True, [2], 1),
            # Compaction keeps the rows but moves them to a new file, which an append would read twice.
            ("a_compaction_rebuilds", "same", [_append_then_compact], False, True, [1, 2, 3], 2),
            ("a_recreated_table_rebuilds", "other", [_append], False, True, [1, 2, 3], 1),
            ("a_cursor_ahead_of_the_table_rebuilds", "ahead", [], False, True, [1, 2], 0),
            # By file, a commit that removes files only replaces the rows of the files it touched.
            ("by_file_an_append_reads_the_new_file", "same", [_append], True, False, [3], 1),
            ("by_file_an_unchanged_table_reads_nothing", "same", [], True, False, [], 0),
            ("by_file_a_delete_reads_nothing_and_drops_the_file", "same", [_delete], True, False, [], 1),
            ("by_file_an_update_reads_the_rewritten_file", "same", [_update], True, False, [10], 1),
            ("by_file_a_merge_reads_the_files_it_wrote", "same", [_merge], True, False, [4, 22], 1),
            ("by_file_an_overwrite_reads_the_new_file", "same", [_overwrite], True, False, [9], 1),
            ("by_file_a_compaction_reads_the_compacted_files", "same", [_append_then_compact], True, False, [2, 3], 2),
            ("by_file_a_recreated_table_rebuilds", "other", [_append], True, True, [1, 2, 3], 1),
            ("by_file_a_cursor_ahead_of_the_table_rebuilds", "ahead", [], True, True, [1, 2], 0),
            (
                "by_file_a_sync_that_named_no_files_rebuilds",
                "same_without_file_names",
                [_append],
                True,
                True,
                [1, 2, 3],
                1,
            ),
        ]
    )
    def test_plan(
        self,
        _name: str,
        stored_cursor: str | None,
        commits: list[Any],
        by_file: bool,
        expected_reset: bool,
        expected_ids: list[int],
        expected_version: int,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "sales")
            write_deltalake(path, pa.table({"id": [1, 2], "day": ["a", "b"]}), partition_by=["day"])
            table_id = str(DeltaTable(path).metadata().id)
            stored = {
                None: None,
                "same": ObjectStorageDeltaCursor(version=0, table_id=table_id, file_names=by_file),
                "same_without_file_names": ObjectStorageDeltaCursor(version=0, table_id=table_id),
                "other": ObjectStorageDeltaCursor(version=0, table_id="another-table", file_names=by_file),
                "ahead": ObjectStorageDeltaCursor(version=5, table_id=table_id, file_names=by_file),
            }[stored_cursor]
            for commit in commits:
                commit(path)

            read = plan_delta_read(path, {}, "sales", stored=stored, by_file=by_file)
            rows = [
                row
                for table in read.iter_tables(with_version=True, with_file_names=by_file)
                for row in table.to_pylist()
            ]
            if by_file and not expected_reset:
                # The destination after the load: the rows of the last sync, less the rows the scope
                # deletes, plus the rows read. It must match the table's current snapshot exactly.
                held = _files_and_ids(path, version=0)
                kept = [(file, row_id) for file, row_id in held if not self._deleted(read.replace_scope, file)]
                loaded = [(row["_file_name"], row["id"]) for row in rows]
                assert sorted(kept + loaded) == _files_and_ids(path)

        assert read.reset_required is expected_reset
        assert read.cursor == ObjectStorageDeltaCursor(version=expected_version, table_id=table_id, file_names=by_file)
        assert sorted(row["id"] for row in rows) == expected_ids
        # Rows read from a subset of the files keep the partition column and carry the version.
        assert all(set(row) == {"id", "day", "_delta_version", *(["_file_name"] if by_file else [])} for row in rows)
        assert {row["_delta_version"] for row in rows} <= {expected_version}
        assert (read.replace_scope is not None) == by_file

    @staticmethod
    def _deleted(scope: ReplaceScope | None, file: str) -> bool:
        return scope is not None and (file in scope.replaced or file not in scope.retained)

    @parameterized.expand([("append", False), ("by_file", True)])
    def test_a_cleaned_up_version_rebuilds(self, _name: str, by_file: bool) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "sales")
            write_deltalake(path, pa.table({"id": [1, 2], "day": ["a", "b"]}))
            table_id = str(DeltaTable(path).metadata().id)
            _append(path)
            DeltaTable(path).create_checkpoint()
            # Log cleanup removes the entries before the checkpoint, so version 0 can no longer be loaded.
            (Path(path) / "_delta_log" / f"{0:020d}.json").unlink()

            read = plan_delta_read(
                path,
                {},
                "sales",
                stored=ObjectStorageDeltaCursor(version=0, table_id=table_id, file_names=by_file),
                by_file=by_file,
            )

        assert read.reset_required is True

    def test_a_storage_failure_loading_the_stored_version_propagates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = str(tmp_path / "sales")
        write_deltalake(path, pa.table({"id": [1, 2], "day": ["a", "b"]}))
        table_id = str(DeltaTable(path).metadata().id)
        _append(path)

        def flaky_table(uri: str, version: int | None = None, **kwargs: Any) -> DeltaTable:
            if version is not None:
                raise OSError("Generic S3 error: request timed out")
            return DeltaTable(uri, **kwargs)

        monkeypatch.setattr(delta, "DeltaTable", flaky_table)

        # A transient failure must be retried, not turned into a rebuild of the whole table.
        with pytest.raises(OSError, match="timed out"):
            plan_delta_read(path, {}, "sales", stored=ObjectStorageDeltaCursor(version=0, table_id=table_id))


class TestFileSelection:
    @parameterized.expand(
        [
            (
                "changed_files_include_the_watermark_and_come_oldest_first",
                "changed",
                1,
                10,
                ["b.csv", "c.csv", "a.csv"],
            ),
            ("new_files_exclude_the_watermark", "new", 1, 10, ["a.csv"]),
            ("a_first_append_reads_every_settled_file", "new", None, 10, ["d.csv", "b.csv", "c.csv", "a.csv"]),
            # The newest file is 30 seconds old, so another file could still get its timestamp.
            ("an_append_leaves_a_file_that_just_landed_for_the_next_sync", "new", 1, 2.5, []),
            ("a_changed_sync_reads_a_file_that_just_landed", "changed", 2, 2.5, ["a.csv"]),
        ]
    )
    def test_select(
        self, _name: str, mode: Any, watermark_minutes: int | None, now_minutes: float, expected: list[str]
    ) -> None:
        def at(minutes: float) -> datetime:
            return MODIFIED_AT + timedelta(minutes=minutes)

        files = [
            StoredObject(path="a.csv", size=1, modified_at=at(2)),
            StoredObject(path="c.csv", size=1, modified_at=at(1)),
            StoredObject(path="b.csv", size=1, modified_at=at(1)),
            StoredObject(path="d.csv", size=1, modified_at=at(0)),
        ]
        selection = FileSelection(mode=mode, watermark=None if watermark_minutes is None else at(watermark_minutes))

        assert [stored.path for stored in selection.select(files, now=at(now_minutes))] == expected

    def test_the_append_settle_window_counts_from_before_the_listing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        listing_started_at = MODIFIED_AT + timedelta(minutes=10)

        monkeypatch.setattr(source_base, "datetime", SimpleNamespace(now=lambda tz=None: listing_started_at))
        for name, age in (("settled.csv", timedelta(minutes=2)), ("fresh.csv", timedelta(seconds=30))):
            (tmp_path / name).write_bytes(b"id\n1\n")
            modified = (listing_started_at - age).timestamp()
            os.utime(tmp_path / name, (modified, modified))
        store = local_store(tmp_path)
        [table] = group_tables(
            store.list_objects("", 10), DiscoveryOptions(combined_table_name="orders"), root_name="root"
        )

        # The real clock is years past both files, so only a cutoff taken before listing leaves the fresh one out.
        rows = [
            row
            for batch in iter_table(store, table, LOGGER, FileSelection(mode="new", watermark=MODIFIED_AT))
            for row in batch.to_pylist()
        ]

        assert {row["_file_name"] for row in rows} == {"settled.csv"}

    @parameterized.expand(
        [
            ("an_unchanged_listing_reads_and_deletes_nothing", [("a.csv", 0, 10), ("b.csv", 1, 10)], None),
            (
                "a_deleted_file_loses_its_rows",
                [("b.csv", 1, 10)],
                (["b.csv"], {"b.csv"}, {"b.csv"}),
            ),
            (
                "a_shrunk_file_replaces_its_rows",
                [("a.csv", 0, 10), ("b.csv", 2, 4)],
                (["b.csv"], {"b.csv"}, {"a.csv", "b.csv"}),
            ),
            (
                "a_renamed_file_moves_its_rows",
                [("renamed.csv", 2, 10), ("b.csv", 1, 10)],
                (["b.csv", "renamed.csv"], {"b.csv", "renamed.csv"}, {"b.csv", "renamed.csv"}),
            ),
        ]
    )
    def test_a_mirrored_read_replaces_the_changed_files_and_drops_the_deleted_ones(
        self,
        _name: str,
        listing: list[tuple[str, int, int]],
        expected: tuple[list[str], set[str], set[str]] | None,
    ) -> None:
        def files(entries: list[tuple[str, int, int]]) -> list[StoredObject]:
            return [
                StoredObject(path=path, size=size, modified_at=MODIFIED_AT + timedelta(minutes=minutes))
                for path, minutes, size in entries
            ]

        last_sync = listing_digest(files([("a.csv", 0, 10), ("b.csv", 1, 10)]))
        selection = FileSelection(mode="changed", watermark=MODIFIED_AT + timedelta(minutes=1))

        plan = plan_mirror(files(listing), selection, last_sync)

        assert len(plan.digest) == 64
        if expected is None:
            assert (plan.files, plan.replace_scope) == ([], None)
            return
        read, replaced, retained = expected
        assert [stored.path for stored in plan.files] == read
        assert plan.replace_scope == ReplaceScope(
            column="_file_name", replaced=frozenset(replaced), retained=frozenset(retained)
        )

    def test_row_numbers_continue_across_the_chunks_of_one_file(self) -> None:
        rows = JSONL_CHUNK_ROWS + 3
        content = b"".join(b'{"n":%d}\n' % number for number in range(rows))

        tables = list(iter_file_tables(io.BytesIO(content), stored("big.jsonl"), "jsonl", CsvOptions()))

        assert len(tables) == 2
        assert [number for table in tables for number in table["_file_row_number"].to_pylist()] == list(range(rows))

    def test_row_numbers_continue_across_the_batches_of_a_gzipped_parquet_file(self) -> None:
        rows = PARQUET_BATCH_ROWS + 3
        buffer = io.BytesIO()
        pq.write_table(pa.table({"n": list(range(rows))}), buffer)
        content = gzip.compress(buffer.getvalue())

        tables = list(iter_file_tables(io.BytesIO(content), stored("big.parquet.gz"), "parquet", CsvOptions()))

        assert len(tables) == 2
        assert [number for table in tables for number in table["_file_row_number"].to_pylist()] == list(range(rows))


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

    def test_a_prefix_of_folder_markers_fails_instead_of_walking_every_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem."
            "MAX_LISTED_KEYS",
            3,
        )
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="secret"
        )
        with Stubber(client) as stubber:
            stubber.add_response(
                "list_objects_v2",
                _listing("exports/a/", "exports/b/", "exports/c/", "exports/d/"),
                {"Bucket": "customer-data", "MaxKeys": 1000, "Prefix": "exports/"},
            )

            with pytest.raises(ObjectStorageError, match=TOO_MANY_FILES_ERROR):
                _s3_store(client).list_objects("", 10)

    @parameterized.expand(
        [
            ("bucket_root", "", "exports/orders-", "exports/orders-", 10),
            ("store_root", "root", "exports/orders-", "root/exports/orders-", 10),
            ("empty_key_prefix", "root", "", "root/", 10),
            ("empty_bucket_prefix", "", "", "", 10),
            ("matching_file_limit", "root", "exports/orders-", "root/exports/orders-", 1),
        ]
    )
    def test_list_key_prefix(
        self, _name: str, prefix: str, key_prefix: str, expected_prefix: str, max_objects: int
    ) -> None:
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="secret"
        )
        root_key = f"{prefix}/" if prefix else ""
        store = S3ObjectStore(
            fs=LocalFileSystem(),
            root=f"customer-data/{prefix}" if prefix else "customer-data",
            delta_uri_prefix="s3://",
            delta_storage_options={},
            client=client,
            bucket="customer-data",
            prefix=prefix,
        )
        with Stubber(client) as stubber:
            stubber.add_response(
                "list_objects_v2",
                _listing(
                    f"{expected_prefix}folder/",
                    f"{root_key}exports/orders-1.csv",
                    f"{root_key}exports/orders-2.csv",
                ),
                {"Bucket": "customer-data", "MaxKeys": 1000, "Prefix": expected_prefix},
            )

            listed = store.list_key_prefix(key_prefix, max_objects)

            stubber.assert_no_pending_responses()
        assert [stored.path for stored in listed] == ["exports/orders-1.csv", "exports/orders-2.csv"][:max_objects]

    def test_rejected_credentials_become_an_access_error(self) -> None:
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="secret"
        )
        with Stubber(client) as stubber:
            stubber.add_client_error("list_objects_v2", service_error_code="InvalidAccessKeyId", http_status_code=403)

            with pytest.raises(PermissionError):
                _s3_store(client).list_objects("", 10)
