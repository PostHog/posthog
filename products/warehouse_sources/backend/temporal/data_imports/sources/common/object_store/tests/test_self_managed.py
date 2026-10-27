import io
import time
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any

import pytest
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.globs import _State

import pyarrow as pa
import structlog
from fsspec.implementations.local import LocalFileSystem
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_s3.source import AmazonS3Source
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_blob.source import AzureBlobSource
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare_r2.source import CloudflareR2Source
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store import source_base
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import CsvOptions
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.csv_types import (
    CsvColumnType,
    UnsupportedCsvColumnError,
    cast_csv_columns,
    csv_column_type,
    csv_column_types_from_columns,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.discovery import (
    TableDefinition,
    resolve_table_files,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    NO_TABLE_FILES_ERROR,
    TOO_MANY_FILES_ERROR,
    ObjectStorageError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem import (
    ObjectStore,
    StoredObject,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.formats import (
    iter_csv_tables,
    iter_file_tables,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.globs import (
    ClickHouseGlob,
    compile_clickhouse_glob,
    glob_key_prefix,
    glob_listing_prefix,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.self_managed import (
    SelfManagedCredential,
    SelfManagedLocation,
    UnmappableTableError,
    needs_preserved_column_names,
    parse_self_managed_url,
    source_format_for,
    table_definition_for,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.google_cloud_storage.source import (
    GoogleCloudStorageSource,
)

R2_ACCOUNT = "0123456789abcdef0123456789abcdef"
LOGGER = structlog.get_logger()


def local_store(root: Path) -> ObjectStore:
    return ObjectStore(fs=LocalFileSystem(), root=str(root.resolve()), delta_uri_prefix="", delta_storage_options={})


def write_files(root: Path, files: dict[str, str]) -> None:
    for path, content in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(content)


class TestParseSelfManagedUrl:
    @parameterized.expand(
        [
            (
                "s3_virtual_hosted_regional",
                "https://exports.s3.eu-west-1.amazonaws.com/events/*.parquet",
                SelfManagedLocation(service="s3", bucket="exports", key="events/*.parquet", region="eu-west-1"),
            ),
            (
                "s3_virtual_hosted_dotted_bucket",
                "https://my.exports.s3.us-east-2.amazonaws.com/a.csv",
                SelfManagedLocation(service="s3", bucket="my.exports", key="a.csv", region="us-east-2"),
            ),
            (
                "s3_virtual_hosted_legacy_dash_region",
                "https://exports.s3-us-west-2.amazonaws.com/a.csv",
                SelfManagedLocation(service="s3", bucket="exports", key="a.csv", region="us-west-2"),
            ),
            (
                "s3_virtual_hosted_global_has_no_region",
                "https://exports.s3.amazonaws.com/a.csv",
                SelfManagedLocation(service="s3", bucket="exports", key="a.csv", region=None),
            ),
            (
                "s3_virtual_hosted_dualstack",
                "https://exports.s3.dualstack.ap-south-1.amazonaws.com/a.csv",
                SelfManagedLocation(service="s3", bucket="exports", key="a.csv", region="ap-south-1"),
            ),
            (
                "s3_external_endpoint_is_us_east_1",
                "https://exports.s3-external-1.amazonaws.com/a.csv",
                SelfManagedLocation(service="s3", bucket="exports", key="a.csv", region="us-east-1"),
            ),
            (
                "s3_path_style_regional",
                "https://s3.eu-central-1.amazonaws.com/exports/2024/*.csv",
                SelfManagedLocation(service="s3", bucket="exports", key="2024/*.csv", region="eu-central-1"),
            ),
            (
                "s3_path_style_global",
                "https://s3.amazonaws.com/exports/a.csv",
                SelfManagedLocation(service="s3", bucket="exports", key="a.csv", region=None),
            ),
            (
                "s3_china",
                "https://exports.s3.cn-north-1.amazonaws.com.cn/a.csv",
                SelfManagedLocation(service="s3", bucket="exports", key="a.csv", region="cn-north-1"),
            ),
            (
                "s3_percent_encoded_key",
                "https://exports.s3.us-east-1.amazonaws.com/daily%20export/a%2Bb.csv",
                SelfManagedLocation(service="s3", bucket="exports", key="daily export/a+b.csv", region="us-east-1"),
            ),
            (
                "s3_http_scheme",
                "http://exports.s3.us-east-1.amazonaws.com/a.csv",
                SelfManagedLocation(service="s3", bucket="exports", key="a.csv", region="us-east-1"),
            ),
            (
                "gcs_path_style",
                "https://storage.googleapis.com/analytics-dump/tables/**.parquet",
                SelfManagedLocation(service="gcs", bucket="analytics-dump", key="tables/**.parquet"),
            ),
            (
                "gcs_virtual_hosted",
                "https://analytics-dump.storage.googleapis.com/a.jsonl",
                SelfManagedLocation(service="gcs", bucket="analytics-dump", key="a.jsonl"),
            ),
            (
                "azure",
                "https://examplestore.blob.core.windows.net/exports/orders/*.csv",
                SelfManagedLocation(service="azure", bucket="exports", key="orders/*.csv", account="examplestore"),
            ),
            (
                "r2",
                f"https://{R2_ACCOUNT}.r2.cloudflarestorage.com/exports/orders/{{1..3}}.csv",
                SelfManagedLocation(service="r2", bucket="exports", key="orders/{1..3}.csv", account=R2_ACCOUNT),
            ),
            (
                "upper_case_host",
                "https://EXPORTS.S3.US-EAST-1.AMAZONAWS.COM/A.csv",
                SelfManagedLocation(service="s3", bucket="exports", key="A.csv", region="us-east-1"),
            ),
        ]
    )
    def test_parses(self, _name: str, url: str, expected: SelfManagedLocation) -> None:
        assert parse_self_managed_url(url) == expected

    @parameterized.expand(
        [
            ("not_http", "s3://exports/a.csv"),
            ("unknown_host", "https://minio.example.com/exports/a.csv"),
            ("s3_website_endpoint", "https://exports.s3-website-us-east-1.amazonaws.com/a.csv"),
            ("s3_access_point", "https://ap-123456789012.s3-accesspoint.us-east-1.amazonaws.com/a.csv"),
            ("s3_accelerate", "https://exports.s3-accelerate.amazonaws.com/a.csv"),
            ("query_string", "https://exports.s3.us-east-1.amazonaws.com/a.csv?versionId=1"),
            ("question_mark_glob", "https://exports.s3.us-east-1.amazonaws.com/a?.csv"),
            ("fragment", "https://exports.s3.us-east-1.amazonaws.com/a.csv#x"),
            ("port", "https://exports.s3.us-east-1.amazonaws.com:8443/a.csv"),
            ("userinfo", "https://user:pass@exports.s3.us-east-1.amazonaws.com/a.csv"),
            ("path_style_without_bucket", "https://s3.us-east-1.amazonaws.com/"),
            ("glob_in_bucket", "https://s3.us-east-1.amazonaws.com/exports-*/a.csv"),
            ("dot_dot_segment", "https://exports.s3.us-east-1.amazonaws.com/a/../b.csv"),
            ("key_with_a_leading_slash", "https://exports.s3.us-east-1.amazonaws.com//orders.csv"),
            ("key_with_an_empty_segment", "https://storage.googleapis.com/lake/orders//a.csv"),
            ("azure_data_lake_endpoint", "https://examplestore.dfs.core.windows.net/exports/a.csv"),
            ("azure_other_cloud", "https://examplestore.blob.core.chinacloudapi.cn/exports/a.csv"),
            ("azure_without_container", "https://examplestore.blob.core.windows.net/"),
            ("r2_jurisdiction_endpoint", f"https://{R2_ACCOUNT}.eu.r2.cloudflarestorage.com/exports/a.csv"),
            ("r2_short_account", "https://abc.r2.cloudflarestorage.com/exports/a.csv"),
            ("gcs_browser_url", "https://storage.cloud.google.com/exports/a.csv"),
        ]
    )
    def test_refuses_urls_it_cant_map_exactly(self, _name: str, url: str) -> None:
        with pytest.raises(UnmappableTableError):
            parse_self_managed_url(url)


class TestClickHouseGlob:
    @parameterized.expand(
        [
            ("star_stays_in_its_folder", "data/*.csv", "data/a.csv", True),
            ("star_matches_empty", "data/*.csv", "data/.csv", True),
            ("star_does_not_cross_folders", "data/*.csv", "data/2024/a.csv", False),
            ("double_star_crosses_folders", "data/**.csv", "data/2024/01/a.csv", True),
            ("double_star_folder", "data/**", "data/x/y", True),
            ("question_mark_is_one_character", "part-?.csv", "part-1.csv", True),
            ("question_mark_is_not_two", "part-?.csv", "part-10.csv", False),
            ("question_mark_does_not_match_slash", "a?b", "a/b", False),
            ("alternatives", "{orders,refunds}.csv", "refunds.csv", True),
            ("alternatives_are_literal", "{a.b,c}.csv", "aXb.csv", False),
            ("range", "part-{1..12}.csv", "part-12.csv", True),
            ("range_upper_bound", "part-{1..12}.csv", "part-13.csv", False),
            ("range_reversed_bounds", "part-{12..1}.csv", "part-5.csv", True),
            ("range_without_padding_refuses_leading_zero", "part-{1..12}.csv", "part-05.csv", False),
            ("padded_range", "part-{01..12}.csv", "part-05.csv", True),
            ("padded_range_refuses_unpadded", "part-{01..12}.csv", "part-5.csv", False),
            ("literal_regex_characters", "a+b(1).csv", "a+b(1).csv", True),
            ("literal_dot_is_not_any_character", "a.csv", "aXcsv", False),
            ("literal_path_is_exact", "data/a.csv", "data/a.csv.bak", False),
            ("hidden_files_match_like_clickhouse", "data/*", "data/_SUCCESS", True),
            ("range_leaves_digits_for_star", "part-{1..12}*.csv", "part-123.csv", True),
            ("range_does_not_take_extra_digits", "part-{1..12}.csv", "part-123.csv", False),
            ("empty_alternative", "{a,}x.csv", "x.csv", True),
            ("padded_range_in_middle", "d={01..31}/h-*.csv", "d=07/h-1.csv", True),
            ("padded_range_in_middle_refuses_unpadded", "d={01..31}/h-*.csv", "d=7/h-1.csv", False),
            ("zero_range", "{0..0}", "0", True),
            ("zero_range_refuses_extra_zero", "{0..0}", "00", False),
            ("double_star_after_range", "{1..12}**.csv", "123/nested/a.csv", True),
            ("alternatives_before_star", "{a,ab}*.csv", "abc.csv", True),
            ("double_star_matches_empty", "**", "", True),
            ("star_does_not_match_slash", "*", "/", False),
            ("question_mark_does_not_match_only_slash", "?", "/", False),
            ("triple_star_crosses_folders", "***", "a/b", True),
            ("four_stars_match_empty", "****", "", True),
            ("adjacent_empty_alternatives", "*{a,}{b,}x", "x", True),
            ("range_leaves_digits_for_literal", "{1..12}3", "123", True),
            ("padded_reversed_range", "{12..01}", "07", True),
            ("padded_range_uses_widest_bound", "{0..0012}", "0007", True),
        ]
    )
    def test_matches(self, _name: str, pattern: str, path: str, expected: bool) -> None:
        assert compile_clickhouse_glob(pattern).matches(path) is expected

    @parameterized.expand(
        [
            ("unclosed_brace", "a{b,c.csv"),
            ("empty_braces", "a{}.csv"),
            ("nested_glob_in_braces", "{a*,b}.csv"),
            ("square_brackets", "part-[0-9].csv"),
            ("stray_closing_brace", "a}.csv"),
            ("nested_question_mark", "{a?,b}.csv"),
            ("nested_brace", "{{a,b},c}.csv"),
            ("bracket_in_braces", "{a[,b}.csv"),
            ("closing_bracket_in_braces", "{a],b}.csv"),
            ("stray_closing_bracket", "a].csv"),
        ]
    )
    def test_refuses_patterns_it_cant_read(self, _name: str, pattern: str) -> None:
        with pytest.raises(ObjectStorageError):
            compile_clickhouse_glob(pattern)

    @parameterized.expand(
        [
            ("glob_in_file_name", "events/2024/*.csv", "events/2024"),
            ("glob_in_folder", "events/*/a.csv", "events"),
            ("glob_at_root", "*.csv", ""),
            ("range_folder", "y={2023..2024}/a.parquet", ""),
            ("literal_file", "events/a.csv", "events/a.csv"),
        ]
    )
    def test_listing_prefix(self, _name: str, pattern: str, expected: str) -> None:
        assert glob_listing_prefix(pattern) == expected

    @parameterized.expand(
        [
            ("glob_in_file_name", "exports/orders-*.csv", "exports/orders-"),
            ("glob_at_root", "*.csv", ""),
            ("range_folder", "y={2023..2024}/a.parquet", "y="),
            ("literal_file", "events/a.csv", "events/a.csv"),
            ("question_mark", "a?b", "a"),
        ]
    )
    def test_key_prefix(self, _name: str, pattern: str, expected: str) -> None:
        assert glob_key_prefix(pattern) == expected

    @parameterized.expand(
        [
            ("twenty_stars", "*a" * 20 + "*b.csv"),
            ("eight_stars", "*a*a*a*a*a*a*a*a*b.csv"),
        ]
    )
    def test_adversarial_match_work_is_bounded(self, _name: str, pattern: str) -> None:
        glob = compile_clickhouse_glob(pattern)
        # Short enough that a backtracking matcher returns and fails the assertions below instead of hanging.
        path = "a" * 20 + ".csv"
        closure = ClickHouseGlob._epsilon_closure
        state_counts: list[int] = []

        def counting_closure(self: ClickHouseGlob, states: set[_State]) -> set[_State]:
            result = closure(self, states)
            state_counts.append(len(result))
            return result

        with patch.object(ClickHouseGlob, "_epsilon_closure", counting_closure):
            assert glob.matches(path) is False

        # One state set per character, each no larger than the token count, keeps the work linear.
        assert 0 < len(state_counts) <= len(path) + 1
        assert max(state_counts) <= len(glob.tokens) + 1
        assert glob.matches("a" * 20 + "b.csv") is True

    @parameterized.expand(
        [
            ("few_matching_keys", 3, False),
            ("matching_key_limit", 2, True),
        ]
    )
    def test_resolves_only_the_key_prefix(self, _name: str, max_objects: int, exceeds_limit: bool) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_files(
                root,
                {
                    "exports/other-1.csv": "id\n1\n",
                    "exports/other-2.csv": "id\n2\n",
                    "exports/other-3.csv": "id\n3\n",
                    "exports/orders-2.csv": "id\n2\n",
                    "exports/orders-1.csv": "id\n1\n",
                    "exports/orders-3.txt": "id\n3\n",
                },
            )
            table = TableDefinition(
                name="orders",
                kind="files",
                path="exports",
                scope="glob",
                file_format="csv",
                csv=CsvOptions(),
                pattern="exports/orders-*.csv",
                source_format="csv",
            )
            if exceeds_limit:
                with pytest.raises(ObjectStorageError, match=f"{TOO_MANY_FILES_ERROR}.*exports/orders-"):
                    resolve_table_files(local_store(root), table, max_objects=max_objects)
            else:
                resolved = resolve_table_files(local_store(root), table, max_objects=max_objects)
                assert [stored.path for stored in resolved.files] == ["exports/orders-1.csv", "exports/orders-2.csv"]


class TestTableDefinition:
    @parameterized.expand(
        [
            ("CSV", "csv_no_header"),
            ("CSVWithNames", "csv"),
            ("Parquet", "parquet"),
            ("JSONEachRow", "jsonl"),
            ("Delta", "delta"),
            ("DeltaS3Wrapper", "delta"),
        ]
    )
    def test_format_mapping(self, table_format: str, expected: str) -> None:
        assert source_format_for(table_format) == expected

    def test_an_unknown_format_is_refused(self) -> None:
        with pytest.raises(UnmappableTableError):
            source_format_for("TabSeparated")

    @parameterized.expand(
        [
            ("all_snake_case", ["id", "created_at", "amount_usd"], False),
            ("no_columns", [], False),
            ("camel_case", ["id", "createdAt"], True),
            ("spaces", ["Order ID"], True),
            ("upper_case", ["ID"], True),
        ]
    )
    def test_preserve_names_only_when_the_pipeline_would_rename(
        self, _name: str, columns: list[str], expected: bool
    ) -> None:
        assert needs_preserved_column_names(columns) is expected

    def test_csv_with_names_keeps_the_stored_types_and_quote_setting(self) -> None:
        location = parse_self_managed_url("https://exports.s3.us-east-1.amazonaws.com/orders/2024-*.csv")
        columns = {
            "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField", "valid": True},
            "Order Total": {"clickhouse": "Nullable(Float64)", "hogql": "FloatDatabaseField", "valid": True},
            "note": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
        }

        definition = table_definition_for("orders", location, "CSVWithNames", columns, csv_allow_double_quotes=False)

        assert definition.schema_metadata() == {
            "kind": "files",
            "scope": "glob",
            "path": "orders",
            "pattern": "orders/2024-*.csv",
            "format": "csv",
            "source_format": "csv",
            "csv": {
                "has_header": True,
                "allow_double_quotes": False,
                "column_types": {"id": "integer", "Order Total": "float"},
                "null_marker": True,
                "delimiter": ",",
            },
            "preserve_column_names": True,
        }

    @parameterized.expand(
        [
            ("csv_without_header", "CSV", "csv_no_header", False, True),
            ("parquet_has_no_csv_types", "Parquet", "parquet", True, False),
            ("jsonl_has_no_csv_types", "JSONEachRow", "jsonl", True, False),
        ]
    )
    def test_csv_header_and_types_follow_the_format(
        self, _name: str, table_format: str, file_format: str, has_header: bool, has_types: bool
    ) -> None:
        location = parse_self_managed_url("https://exports.s3.us-east-1.amazonaws.com/orders/a.file")
        columns = {"c1": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"}}

        definition = table_definition_for("orders", location, table_format, columns, None)

        assert (definition.scope, definition.path, definition.file_format) == ("glob", "orders/a.file", file_format)
        assert definition.csv.allow_double_quotes is True
        assert definition.csv.has_header is (has_header if file_format.startswith("csv") else False)
        assert bool(definition.csv.column_types) is has_types

    @parameterized.expand([("Delta",), ("DeltaS3Wrapper",)])
    def test_delta_reads_the_table_folder(self, table_format: str) -> None:
        location = parse_self_managed_url("https://storage.googleapis.com/lake/tables/orders/")

        definition = table_definition_for("orders", location, table_format, {"OrderId": "Int64"}, None)

        assert (definition.kind, definition.path, definition.pattern) == ("delta", "tables/orders", None)
        assert definition.preserve_column_names is True

    @parameterized.expand(
        [
            ("delta_with_glob", "https://storage.googleapis.com/lake/tables/*", "Delta"),
            ("files_url_is_a_folder", "https://storage.googleapis.com/lake/tables/", "Parquet"),
            ("files_url_is_the_bucket", "https://storage.googleapis.com/lake", "CSVWithNames"),
            ("unreadable_glob", "https://storage.googleapis.com/lake/part-[0-9].parquet", "Parquet"),
        ]
    )
    def test_refuses_tables_it_cant_read_exactly(self, _name: str, url: str, table_format: str) -> None:
        with pytest.raises(UnmappableTableError):
            table_definition_for("orders", parse_self_managed_url(url), table_format, {}, None)

    def test_metadata_round_trip_keeps_the_glob_types_and_names(self) -> None:
        location = parse_self_managed_url("https://exports.s3.us-east-1.amazonaws.com/orders/{1..3}.csv")
        definition = table_definition_for(
            "orders", location, "CSVWithNames", {"OrderId": "Nullable(Int64)", "paid": "Bool"}, None
        )

        rebuilt = TableDefinition.from_schema_metadata("orders", definition.schema_metadata())

        assert rebuilt == definition

    def test_metadata_round_trip_keeps_decimal_unsigned_and_time_zone_types(self) -> None:
        location = parse_self_managed_url("https://exports.s3.us-east-1.amazonaws.com/orders/*.csv")
        columns = {
            "total": "Nullable(Decimal(12, 3))",
            "big": "UInt64",
            "at": "DateTime64(3, 'Europe/London')",
            "utc": "DateTime('UTC')",
        }
        definition = table_definition_for("orders", location, "CSVWithNames", columns, None)

        metadata = definition.schema_metadata()
        rebuilt = TableDefinition.from_schema_metadata("orders", metadata)

        assert metadata["csv"]["column_types"] == {
            "total": {"kind": "decimal", "precision": 12, "scale": 3},
            "big": "unsigned",
            "at": {"kind": "datetime", "timezone": "Europe/London"},
            "utc": "datetime",
        }
        assert rebuilt == definition

    @parameterized.expand(
        [
            (f"{table_format}_{column_type}", table_format, column_type, url)
            for table_format, url in (
                ("Parquet", "https://storage.googleapis.com/lake/orders/*.parquet"),
                ("JSONEachRow", "https://storage.googleapis.com/lake/orders/*.jsonl"),
                ("CSVWithNames", "https://storage.googleapis.com/lake/orders/*.csv"),
                ("Delta", "https://storage.googleapis.com/lake/orders/"),
            )
            for column_type in (
                "Array(Nullable(Int64))",
                "Map(String, String)",
                "Tuple(a Nullable(Int64), b Nullable(String))",
                "Nullable(JSON)",
                "Object('json')",
                "Nested(a Int64)",
            )
        ]
    )
    def test_nested_columns_are_refused(self, _name: str, table_format: str, column_type: str, url: str) -> None:
        columns = {"id": "Int64", "items": {"clickhouse": column_type, "hogql": "StringJSONDatabaseField"}}

        with pytest.raises(UnmappableTableError, match="'items'"):
            table_definition_for("orders", parse_self_managed_url(url), table_format, columns, None)

    def test_an_invalid_nested_column_does_not_block_the_table(self) -> None:
        location = parse_self_managed_url("https://storage.googleapis.com/lake/orders/*.parquet")
        columns = {"items": {"clickhouse": "Array(Int64)", "hogql": "StringArrayDatabaseField", "valid": False}}

        assert table_definition_for("orders", location, "Parquet", columns, None).kind == "files"

    def test_a_csv_column_no_import_keeps_is_refused(self) -> None:
        location = parse_self_managed_url("https://storage.googleapis.com/lake/orders/*.csv")

        with pytest.raises(UnmappableTableError, match="'id'"):
            table_definition_for("orders", location, "CSVWithNames", {"id": "Int128"}, None)

    @parameterized.expand(
        [
            (f"{table_format}_{column}", table_format, column, url)
            for table_format, url in (
                ("Parquet", "https://storage.googleapis.com/lake/orders/*.parquet"),
                ("CSVWithNames", "https://storage.googleapis.com/lake/orders/*.csv"),
                ("Delta", "https://storage.googleapis.com/lake/orders/"),
            )
            for column in ("_file_name", "_file_modified_at", "_file_row_number")
        ]
    )
    def test_columns_named_like_the_file_columns_are_refused(
        self, _name: str, table_format: str, column: str, url: str
    ) -> None:
        columns = {"id": "Int64", column: "Nullable(String)"}

        with pytest.raises(UnmappableTableError, match=f"'{column}'"):
            table_definition_for("orders", parse_self_managed_url(url), table_format, columns, None)

    @parameterized.expand([("Date",), ("Nullable(Date32)",), ("DateTime",), ("Nullable(DateTime64(9))",)])
    def test_json_dates_and_times_are_refused(self, column_type: str) -> None:
        location = parse_self_managed_url("https://storage.googleapis.com/lake/orders/*.jsonl")

        with pytest.raises(UnmappableTableError, match="'created'"):
            table_definition_for("orders", location, "JSONEachRow", {"id": "Int64", "created": column_type}, None)

    def test_csv_header_names_with_surrounding_spaces_are_refused(self) -> None:
        location = parse_self_managed_url("https://storage.googleapis.com/lake/orders/*.csv")

        with pytest.raises(UnmappableTableError, match="' Order ID '"):
            table_definition_for("orders", location, "CSVWithNames", {" Order ID ": "Nullable(String)"}, None)

    def test_headerless_csv_names_are_not_checked_for_spaces(self) -> None:
        location = parse_self_managed_url("https://storage.googleapis.com/lake/orders/*.csv")

        assert table_definition_for("orders", location, "CSV", {"c1": "Nullable(String)"}, None).kind == "files"

    @parameterized.expand(
        [
            ("glob_without_pattern", {"kind": "files", "scope": "glob", "path": "", "format": "csv"}),
            ("unknown_scope", {"kind": "files", "scope": "everything", "path": "", "format": "csv"}),
        ]
    )
    def test_unusable_glob_metadata_is_ignored(self, _name: str, metadata: dict[str, Any]) -> None:
        assert TableDefinition.from_schema_metadata("orders", metadata) is None

    def test_unknown_column_kinds_in_metadata_are_dropped(self) -> None:
        rebuilt = TableDefinition.from_schema_metadata(
            "orders",
            {
                "kind": "files",
                "scope": "glob",
                "path": "",
                "pattern": "*.csv",
                "format": "csv",
                "csv": {"column_types": {"id": "integer", "blob": "binary", "n": 3}},
            },
        )

        assert rebuilt is not None
        assert rebuilt.csv.column_types == (CsvColumnType(name="id", kind="integer"),)
        assert rebuilt.preserve_column_names is False


class TestResolveGlobFiles:
    def test_reads_exactly_the_files_the_glob_matches(self, tmp_path: Path) -> None:
        write_files(
            tmp_path,
            {
                "orders/part-1.csv": "id\n1\n",
                "orders/part-2.csv": "id\n2\n",
                "orders/part-3.csv": "id\n3\n",
                "orders/_SUCCESS": "",
                "orders/nested/part-1.csv": "id\n4\n",
                "orders/part-1.csv.bak": "id\n5\n",
                "refunds/part-1.csv": "id\n6\n",
            },
        )
        location = parse_self_managed_url("https://exports.s3.us-east-1.amazonaws.com/orders/part-{1..2}.csv")
        table = table_definition_for("orders", location, "CSVWithNames", {}, None)

        resolved = resolve_table_files(local_store(tmp_path), table)

        assert [stored.path for stored in resolved.files] == ["orders/part-1.csv", "orders/part-2.csv"]

    def test_a_literal_file_resolves_to_that_file(self, tmp_path: Path) -> None:
        write_files(tmp_path, {"orders.csv": "id\n1\n", "orders.csv.old": "id\n2\n"})
        location = parse_self_managed_url("https://exports.s3.us-east-1.amazonaws.com/orders.csv")
        table = table_definition_for("orders", location, "CSVWithNames", {}, None)

        resolved = resolve_table_files(local_store(tmp_path), table)

        assert [stored.path for stored in resolved.files] == ["orders.csv"]

    def test_no_matching_file_is_a_missing_table(self, tmp_path: Path) -> None:
        write_files(tmp_path, {"orders/a.parquet": "x"})
        location = parse_self_managed_url("https://exports.s3.us-east-1.amazonaws.com/orders/*.csv")
        table = table_definition_for("orders", location, "CSVWithNames", {}, None)

        with pytest.raises(ObjectStorageError, match=NO_TABLE_FILES_ERROR):
            resolve_table_files(local_store(tmp_path), table)


class TestCsvColumnTypes:
    @parameterized.expand(
        [
            ("Int64", CsvColumnType(name="c", kind="integer")),
            ("Nullable(Int32)", CsvColumnType(name="c", kind="integer")),
            ("UInt8", CsvColumnType(name="c", kind="integer")),
            ("LowCardinality(Nullable(Int16))", CsvColumnType(name="c", kind="integer")),
            ("UInt64", CsvColumnType(name="c", kind="unsigned")),
            ("Nullable(UInt64)", CsvColumnType(name="c", kind="unsigned")),
            ("Float32", CsvColumnType(name="c", kind="float")),
            ("Nullable(Float64)", CsvColumnType(name="c", kind="float")),
            ("Decimal(10, 2)", CsvColumnType(name="c", kind="decimal", precision=10, scale=2)),
            ("Nullable(Decimal(38,0))", CsvColumnType(name="c", kind="decimal", precision=38, scale=0)),
            ("Decimal32(4)", CsvColumnType(name="c", kind="decimal", precision=9, scale=4)),
            ("Decimal64(6)", CsvColumnType(name="c", kind="decimal", precision=18, scale=6)),
            ("Decimal128(10)", CsvColumnType(name="c", kind="decimal", precision=38, scale=10)),
            ("Bool", CsvColumnType(name="c", kind="boolean")),
            ("Date", CsvColumnType(name="c", kind="date")),
            ("Date32", CsvColumnType(name="c", kind="date")),
            ("DateTime", CsvColumnType(name="c", kind="datetime")),
            ("Nullable(DateTime64(6, 'UTC'))", CsvColumnType(name="c", kind="datetime")),
            ("DateTime('Europe/London')", CsvColumnType(name="c", kind="datetime", timezone="Europe/London")),
            (
                "Nullable(DateTime64(3, 'America/New_York'))",
                CsvColumnType(name="c", kind="datetime", timezone="America/New_York"),
            ),
            ("String", None),
            ("Array(Int64)", None),
            ("Nullable(UUID)", None),
            ("", None),
        ]
    )
    def test_type_for_stored_type(self, clickhouse_type: str, expected: CsvColumnType | None) -> None:
        assert csv_column_type("c", clickhouse_type) == expected

    @parameterized.expand(
        [
            ("int128", "Int128"),
            ("uint256", "Nullable(UInt256)"),
            ("decimal_wider_than_38_digits", "Decimal(50, 2)"),
            ("decimal256", "Decimal256(4)"),
            ("decimal_without_arguments", "Decimal"),
            ("unknown_time_zone", "DateTime('Nowhere/Land')"),
        ]
    )
    def test_types_no_import_keeps_are_refused(self, _name: str, clickhouse_type: str) -> None:
        with pytest.raises(UnsupportedCsvColumnError, match="'c'"):
            csv_column_type("c", clickhouse_type)

    def test_types_from_stored_columns_skip_invalid_and_string_columns(self) -> None:
        columns: dict[str, Any] = {
            "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField", "valid": True},
            "broken": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField", "valid": False},
            "legacy": "Nullable(Float64)",
            "name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
            "odd": 5,
        }

        assert csv_column_types_from_columns(columns) == (
            CsvColumnType(name="id", kind="integer"),
            CsvColumnType(name="legacy", kind="float"),
        )

    @parameterized.expand(
        [
            ("integers", "integer", ["1", " -2 ", "+3", None, ""], [1, -2, 3, None, None], 0),
            (
                "bad_integers_become_null",
                "integer",
                ["1", "1.5", "x", "99999999999999999999"],
                [1, None, None, None],
                3,
            ),
            ("floats", "float", ["1.5", "1e3", " 2 ", "-0.25", "+4"], [1.5, 1000.0, 2.0, -0.25, 4.0], 0),
            ("bad_floats_become_null", "float", ["1.5", "one"], [1.5, None], 1),
            (
                "booleans",
                "boolean",
                ["true", "FALSE", "1", "0", "yes", "No", None],
                [True, False, True, False, True, False, None],
                0,
            ),
            ("bad_booleans_become_null", "boolean", ["true", "maybe"], [True, None], 1),
            ("dates", "date", ["2024-01-15", "1999-12-31"], [date(2024, 1, 15), date(1999, 12, 31)], 0),
            (
                "bad_dates_become_null",
                "date",
                ["2024-01-15", "2024-13-01", "15/01/2024"],
                [date(2024, 1, 15), None, None],
                2,
            ),
            (
                "naive_datetimes_are_utc",
                "datetime",
                ["2024-01-15 10:30:00", "2024-01-15T10:30:00.123456"],
                [datetime(2024, 1, 15, 10, 30, tzinfo=UTC), datetime(2024, 1, 15, 10, 30, 0, 123456, tzinfo=UTC)],
                0,
            ),
            (
                "datetimes_with_offsets",
                "datetime",
                ["2024-01-15T10:30:00Z", "2024-01-15T10:30:00+02:00"],
                [datetime(2024, 1, 15, 10, 30, tzinfo=UTC), datetime(2024, 1, 15, 8, 30, tzinfo=UTC)],
                0,
            ),
            (
                "mixed_datetimes_are_read_one_by_one",
                "datetime",
                ["2024-01-15 10:30:00", "2024-01-15T10:30:00Z", "soon"],
                [datetime(2024, 1, 15, 10, 30, tzinfo=UTC), datetime(2024, 1, 15, 10, 30, tzinfo=UTC), None],
                1,
            ),
            (
                "unsigned_keeps_values_above_int64",
                CsvColumnType(name="value", kind="unsigned"),
                ["18446744073709551615", "0", "-1", "+7", "18446744073709551616"],
                [Decimal(18446744073709551615), Decimal(0), None, Decimal(7), None],
                2,
            ),
            (
                "decimals_keep_their_scale",
                CsvColumnType(name="value", kind="decimal", precision=10, scale=2),
                ["1.25", "-3.1", "7", "1.255", "x", "123456789012.5"],
                [Decimal("1.25"), Decimal("-3.10"), Decimal("7.00"), Decimal("1.25"), None, None],
                2,
            ),
            (
                "naive_datetimes_take_the_column_time_zone",
                CsvColumnType(name="value", kind="datetime", timezone="Europe/London"),
                ["2024-07-01 10:00:00", "2024-01-15 10:00:00"],
                [datetime(2024, 7, 1, 9, 0, tzinfo=UTC), datetime(2024, 1, 15, 10, 0, tzinfo=UTC)],
                0,
            ),
            (
                "offsets_win_over_the_column_time_zone",
                CsvColumnType(name="value", kind="datetime", timezone="Europe/London"),
                ["2024-07-01T10:00:00Z", "2024-07-01T10:00:00+02:00"],
                [datetime(2024, 7, 1, 10, 0, tzinfo=UTC), datetime(2024, 7, 1, 8, 0, tzinfo=UTC)],
                0,
            ),
            (
                "mixed_values_in_a_time_zone_are_read_one_by_one",
                CsvColumnType(name="value", kind="datetime", timezone="Europe/London"),
                ["2024-07-01 10:00:00", "2024-07-01T10:00:00Z", "soon"],
                [datetime(2024, 7, 1, 9, 0, tzinfo=UTC), datetime(2024, 7, 1, 10, 0, tzinfo=UTC), None],
                1,
            ),
            (
                "nanosecond_datetimes_are_truncated_to_microseconds",
                "datetime",
                ["2024-07-01 10:00:00.123456789", "2024-07-01 10:00:00", "2024-07-01T10:00:00.123456789+02:00"],
                [
                    datetime(2024, 7, 1, 10, 0, 0, 123456, tzinfo=UTC),
                    datetime(2024, 7, 1, 10, 0, tzinfo=UTC),
                    datetime(2024, 7, 1, 8, 0, 0, 123456, tzinfo=UTC),
                ],
                0,
            ),
            (
                "nanosecond_datetimes_take_the_column_time_zone",
                CsvColumnType(name="value", kind="datetime", timezone="Europe/London"),
                ["2024-07-01 10:00:00.123456789"],
                [datetime(2024, 7, 1, 9, 0, 0, 123456, tzinfo=UTC)],
                0,
            ),
            (
                "repeated_local_time_takes_the_earlier_instant",
                CsvColumnType(name="value", kind="datetime", timezone="Europe/London"),
                ["2024-10-27 01:30:00"],
                [datetime(2024, 10, 27, 0, 30, tzinfo=UTC)],
                0,
            ),
        ]
    )
    def test_cast(
        self, _name: str, kind: Any, values: list[str | None], expected: list[Any], expected_nulled: int
    ) -> None:
        table = pa.table({"value": pa.array(values, pa.string()), "other": pa.array(["x"] * len(values))})
        column_type = kind if isinstance(kind, CsvColumnType) else CsvColumnType(name="value", kind=kind)

        result = cast_csv_columns(table, (column_type,))

        assert result.table.column("value").to_pylist() == expected
        assert result.table.column("other").type == pa.string()
        assert result.nulled_values == ({"value": expected_nulled} if expected_nulled else {})

    def test_a_column_missing_from_the_file_is_ignored(self) -> None:
        table = pa.table({"id": pa.array(["1"])})

        result = cast_csv_columns(table, (CsvColumnType(name="gone", kind="integer"),))

        assert result.table.equals(table)

    @parameterized.expand(
        [
            ("no_bad_values", 1000, ()),
            ("one_bad_value", 1000, (517,)),
            ("bad_first_and_last", 1000, (0, 999)),
            ("bad_values_in_one_run", 1000, tuple(range(300, 340))),
            ("scattered_bad_values", 5000, tuple(range(0, 5000, 97))),
            ("every_value_bad", 200, tuple(range(200))),
            ("shorter_than_one_slice", 5, (2,)),
        ]
    )
    def test_split_cast_equals_a_value_by_value_cast(self, _name: str, rows: int, bad_rows: tuple[int, ...]) -> None:
        bad = set(bad_rows)
        values = [None if row % 11 == 0 else ("x" if row in bad else str(row)) for row in range(rows)]
        table = pa.table({"value": pa.array(values, pa.string())})

        result = cast_csv_columns(table, (CsvColumnType(name="value", kind="integer"),))

        expected = [None if value is None or value == "x" else int(value) for value in values]
        assert result.table.column("value").to_pylist() == expected
        bad_non_null = sum(1 for value in values if value == "x")
        assert result.nulled_values == ({"value": bad_non_null} if bad_non_null else {})

    def test_split_cast_parses_far_fewer_slices_than_values(self) -> None:
        values = [str(row) for row in range(100_000)]
        values[54_321] = "x"
        table = pa.table({"value": pa.array(values, pa.string())})

        started = time.perf_counter()
        result = cast_csv_columns(table, (CsvColumnType(name="value", kind="integer"),))

        assert time.perf_counter() - started < 1
        assert result.nulled_values == {"value": 1}

    def test_the_reader_casts_typed_columns_and_reports_bad_values(self) -> None:
        logger = MagicMock()
        content = b"id,amount,created,label\n1,2.5,2024-01-01,a\nx,3,2024-01-02,b\n"
        options = CsvOptions(
            column_types=(
                CsvColumnType(name="id", kind="integer"),
                CsvColumnType(name="amount", kind="float"),
                CsvColumnType(name="created", kind="date"),
            )
        )

        [table] = list(iter_csv_tables(io.BytesIO(content), options, file_path="orders.csv", logger=logger))

        assert table.schema.types == [pa.int64(), pa.float64(), pa.date32(), pa.string()]
        assert table.column("id").to_pylist() == [1, None]
        logger.warning.assert_called_once()
        assert logger.warning.call_args.kwargs["nulled_values"] == {"id": 1}

    def test_a_header_only_file_gets_typed_empty_columns(self) -> None:
        options = CsvOptions(column_types=(CsvColumnType(name="id", kind="integer"),))

        [table] = list(iter_csv_tables(io.BytesIO(b"id,label\n"), options))

        assert table.num_rows == 0
        assert table.schema.types == [pa.int64(), pa.string()]

    @parameterized.expand(
        [
            ("migrated_table", True, [None, "\\N", "a"]),
            ("new_source", False, ["\\N", "\\N", "a"]),
        ]
    )
    def test_an_unquoted_null_marker_is_null_only_for_migrated_tables(
        self, _name: str, null_marker: bool, expected: list[str | None]
    ) -> None:
        content = b'label\n\\N\n"\\N"\na\n'

        [table] = list(iter_csv_tables(io.BytesIO(content), CsvOptions(null_marker=null_marker)))

        assert table.column("label").to_pylist() == expected

    def test_a_fixed_delimiter_wins_over_the_file_name(self) -> None:
        content = io.BytesIO(b"id,label\n1,a\n")
        stored = StoredObject(path="orders.tsv", size=0, modified_at=datetime(2024, 1, 1, tzinfo=UTC))

        [table] = list(iter_file_tables(content, stored, "csv", CsvOptions(delimiter=",")))

        assert table.column("label").to_pylist() == ["a"]

    def test_new_csv_sources_still_read_strings(self) -> None:
        [table] = list(iter_csv_tables(io.BytesIO(b"id\n1\n"), CsvOptions()))

        assert table.schema.types == [pa.string()]


def _credential(access_key: str = "AKIAEXAMPLE", access_secret: str = "c2VjcmV0") -> SelfManagedCredential:
    return SelfManagedCredential(access_key=access_key, access_secret=access_secret)


@pytest.fixture
def resolvable_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    # The location check resolves the host, and the example hosts here don't exist.
    monkeypatch.setattr(source_base, "validate_warehouse_table_url_pattern", lambda _url: (True, ""))


@pytest.mark.usefixtures("resolvable_hosts")
class TestJobInputsForSelfManaged:
    @parameterized.expand(
        [
            (
                "s3",
                AmazonS3Source,
                "https://exports.s3.eu-west-1.amazonaws.com/a.csv",
                {"url_pattern": "https://s3.eu-west-1.amazonaws.com/exports/", "access_key_id": "AKIAEXAMPLE"},
            ),
            (
                "gcs",
                GoogleCloudStorageSource,
                "https://storage.googleapis.com/exports/a.csv",
                {"url_pattern": "https://storage.googleapis.com/exports/", "access_key_id": "AKIAEXAMPLE"},
            ),
            (
                "r2",
                CloudflareR2Source,
                f"https://{R2_ACCOUNT}.r2.cloudflarestorage.com/exports/a.csv",
                {
                    "url_pattern": f"https://{R2_ACCOUNT}.r2.cloudflarestorage.com/exports/",
                    "access_key_id": "AKIAEXAMPLE",
                },
            ),
        ]
    )
    def test_maps_the_bucket_and_credential(
        self, _name: str, source_class: type, url: str, expected: dict[str, str]
    ) -> None:
        job_inputs = source_class().job_inputs_for_self_managed(parse_self_managed_url(url), _credential())

        assert {key: job_inputs[key] for key in expected} == expected
        assert job_inputs["secret_access_key"] == "c2VjcmV0"
        file_format = job_inputs["file_format"]
        selection = file_format["selection"] if isinstance(file_format, dict) else file_format
        assert selection == "infer"

    def test_azure_takes_the_account_from_the_url_and_the_key_from_the_secret(self) -> None:
        location = parse_self_managed_url("https://examplestore.blob.core.windows.net/exports/a.csv")

        job_inputs = AzureBlobSource().job_inputs_for_self_managed(location, _credential(access_key="ExampleStore"))

        assert (job_inputs["url_pattern"], job_inputs["account_key"]) == (
            "https://examplestore.blob.core.windows.net/exports/",
            "c2VjcmV0",
        )

    @parameterized.expand(
        [
            ("s3_without_region", AmazonS3Source, "https://exports.s3.amazonaws.com/a.csv", _credential()),
            ("s3_bucket_name_too_short", AmazonS3Source, "https://s3.us-east-1.amazonaws.com/ab/a.csv", _credential()),
            (
                "s3_empty_secret",
                AmazonS3Source,
                "https://exports.s3.us-east-1.amazonaws.com/a.csv",
                _credential(access_secret=" "),
            ),
            (
                "azure_key_for_another_account",
                AzureBlobSource,
                "https://examplestore.blob.core.windows.net/exports/a.csv",
                _credential(access_key="otherstore"),
            ),
            (
                "azure_key_that_is_not_base64",
                AzureBlobSource,
                "https://examplestore.blob.core.windows.net/exports/a.csv",
                _credential(access_key="examplestore", access_secret="a;EndpointSuffix=example.com"),
            ),
        ]
    )
    def test_refuses_what_the_source_would_refuse(
        self, _name: str, source_class: type, url: str, credential: SelfManagedCredential
    ) -> None:
        with pytest.raises(UnmappableTableError):
            source_class().job_inputs_for_self_managed(parse_self_managed_url(url), credential)


class TestSourceForPipeline:
    @parameterized.expand([("preserved", True), ("normalized", False)])
    def test_the_response_carries_the_column_name_choice(self, _name: str, preserve: bool) -> None:
        source = AmazonS3Source()
        location = parse_self_managed_url("https://exports.s3.us-east-1.amazonaws.com/orders/*.csv")
        definition = table_definition_for("orders", location, "CSVWithNames", {}, None)
        metadata = {**definition.schema_metadata(), "preserve_column_names": preserve}
        config = source.parse_config(
            {
                "url_pattern": "https://s3.us-east-1.amazonaws.com/exports/",
                "access_key_id": "AKIAEXAMPLE",
                "secret_access_key": "c2VjcmV0",
            }
        )
        inputs = SourceInputs(
            schema_name="orders",
            schema_id=str(uuid.uuid4()),
            source_id=str(uuid.uuid4()),
            team_id=1,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            incremental_field=None,
            incremental_field_type=None,
            job_id=str(uuid.uuid4()),
            logger=LOGGER,
            reset_pipeline=False,
            schema_metadata=metadata,
        )
        source.open_store = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]

        response = source.source_for_pipeline(config, inputs)

        assert response.preserve_column_names is preserve
