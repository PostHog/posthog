import os
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from unittest.mock import patch

import pyarrow as pa
import structlog
from deltalake import write_deltalake
from fsspec import AbstractFileSystem
from fsspec.implementations.local import LocalFileSystem

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import validate_incremental_sync
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_s3.source import AmazonS3Source
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store import source_base
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    ObjectStoreConfig,
    StoreConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    ACCESS_DENIED_ERROR,
    INVALID_CONFIG_ERROR,
    NO_IMPORTABLE_FILES_ERROR,
    NO_SUCH_BUCKET_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem import ObjectStore
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import source_inputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import ReplaceScope, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amazons3 import (
    AmazonS3SourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSchemaSyncType, IncrementalFieldType

# Old enough that an append-only sync treats every file as settled, whatever the real clock says.
FIRST_MODIFIED_AT = datetime(2024, 5, 1, 12, 0, tzinfo=UTC)


class _DeniedFileSystem(LocalFileSystem):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def find(self, path: str, *args: Any, **kwargs: Any) -> Any:
        raise self.error


class _LocalAmazonS3Source(AmazonS3Source):
    """Serves the bucket from a local folder: `<root>/<bucket>/<prefix>`."""

    def __init__(self, root: Path, fs: AbstractFileSystem | None = None) -> None:
        self.root = root.resolve()
        self.fs = fs or LocalFileSystem()

    def open_store(self, store_config: StoreConfig) -> ObjectStore:
        assert isinstance(store_config, ObjectStoreConfig)
        assert (store_config.bucket, store_config.region) == ("customer-data", "us-east-1")
        folder = self.root / store_config.bucket / store_config.prefix
        return ObjectStore(fs=self.fs, root=str(folder).rstrip("/"), delta_uri_prefix="", delta_storage_options={})


def url(key: str) -> str:
    return f"https://customer-data.s3.us-east-1.amazonaws.com/{key}"


def make_config(**overrides: Any) -> AmazonS3SourceConfig:
    values: dict[str, Any] = {
        "url_pattern": url("exports/"),
        "access_key_id": "AKIAEXAMPLE",
        "secret_access_key": "secret",
        **overrides,
    }
    return AmazonS3SourceConfig.from_dict(values)


def write(root: Path, relative: str, content: bytes, modified_at: datetime | None = None) -> None:
    path = root / "customer-data" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if modified_at is not None:
        os.utime(path, (modified_at.timestamp(), modified_at.timestamp()))


def read_rows(source: AmazonS3Source, config: AmazonS3SourceConfig, schema_name: str, metadata: Any) -> list[dict]:
    inputs = source_inputs(schema_name)
    inputs.schema_metadata = metadata
    response = source.source_for_pipeline(config, inputs)
    return [row for table in cast(Iterable[pa.Table], response.items()) for row in table.to_pylist()]


@pytest.mark.parametrize("with_metadata", [True, False])
def test_sync_reads_the_table_discovery_offered(tmp_path: Path, with_metadata: bool) -> None:
    write(tmp_path, "exports/orders/a.csv", b"id,total\n1,10\n")
    write(tmp_path, "exports/orders/b.csv", b"id,total\n2,20\n")
    write(tmp_path, "exports/orders/archive/c.csv", b"id,total\n3,30\n")
    source = _LocalAmazonS3Source(tmp_path)
    config = make_config()
    schemas = {schema.name: schema for schema in source.get_schemas(config, team_id=1)}
    assert set(schemas) == {"orders", "orders_archive"}
    # The pipeline stores the metadata as JSON on the schema row.
    metadata = json.loads(json.dumps(schemas["orders"].schema_metadata)) if with_metadata else None

    rows = read_rows(source, config, "orders", metadata)

    assert [(row["id"], row["_file_name"]) for row in rows] == [("1", "orders/a.csv"), ("2", "orders/b.csv")]


@pytest.mark.parametrize(
    "key, expected",
    [
        # Hive partition folders under the URL's folder fold into one table named after that folder.
        ("exports/orders/**/*.parquet", {"orders": ("files", "", "**/*.parquet")}),
        ("exports/*.csv", {"a": ("files", "a.csv", "*.csv")}),
        ("exports/**.csv", {"a": ("files", "a.csv", "**.csv"), "daily": ("files", "daily", "**.csv")}),
        ("exports/orders", {"orders": ("files", "orders", None)}),
        ("exports/a.csv", {"a": ("files", "a.csv", None)}),
        ("exports/sales/", {"sales": ("delta", "", None)}),
        ("exports/sales", {"sales": ("delta", "sales", None)}),
        (
            "exports/",
            {
                "a": ("files", "a.csv", None),
                "daily": ("files", "daily", None),
                "orders": ("files", "orders", None),
                "sales": ("delta", "sales", None),
            },
        ),
    ],
)
def test_the_url_selects_the_tables(tmp_path: Path, key: str, expected: dict[str, tuple[str, str, str | None]]) -> None:
    for relative in (
        "exports/a.csv",
        "exports/daily/b.csv",
        "exports/orders/_part_key=2024-w10/part-0.parquet",
        "exports/orders/_part_key=2024-w11/part-0.parquet",
        "exports/orders/_part_key=2024-w11/_SUCCESS",
        "exports/sales/_delta_log/00000000000000000000.json",
        "exports/sales/part-0.parquet",
    ):
        write(tmp_path, relative, b"")

    schemas = _LocalAmazonS3Source(tmp_path).get_schemas(make_config(url_pattern=url(key)), team_id=1)

    assert {
        schema.name: (
            schema.schema_metadata["kind"],
            schema.schema_metadata["path"],
            schema.schema_metadata["pattern"],
        )
        for schema in schemas
        if schema.schema_metadata is not None
    } == expected


def test_sync_reads_only_the_files_the_url_matches(tmp_path: Path) -> None:
    write(tmp_path, "exports/orders/a-1.csv", b"id\n1\n")
    write(tmp_path, "exports/orders/a-2.csv", b"id\n2\n")
    source = _LocalAmazonS3Source(tmp_path)
    config = make_config(url_pattern=url("exports/**-1.csv"))
    [schema] = source.get_schemas(config, team_id=1)

    rows = read_rows(source, config, schema.name, schema.schema_metadata)

    assert [(row["id"], row["_file_name"]) for row in rows] == [("1", "orders/a-1.csv")]


def test_sync_keeps_the_settings_the_table_was_discovered_with(tmp_path: Path) -> None:
    write(tmp_path, "exports/raw/a.txt", b"1,2\n")
    source = _LocalAmazonS3Source(tmp_path)
    [schema] = source.get_schemas(make_config(file_format="csv_no_header"), team_id=1)

    rows = read_rows(source, make_config(file_format="infer"), schema.name, schema.schema_metadata)

    assert rows[0]["c1"] == "1"


@pytest.mark.parametrize(
    "files, config_overrides, fs_error, expected",
    [
        ({"exports/a.csv": b"id\n1\n"}, {}, None, None),
        ({"exports/notes.md": b"# hi"}, {}, None, NO_IMPORTABLE_FILES_ERROR),
        ({}, {"url_pattern": "https://s3.us-east-1.amazonaws.com/Not_A_Bucket/exports/"}, None, INVALID_CONFIG_ERROR),
        ({}, {"url_pattern": "https://customer-data.s3.amazonaws.com/exports/"}, None, INVALID_CONFIG_ERROR),
        ({}, {}, PermissionError("Access Denied"), ACCESS_DENIED_ERROR),
        ({}, {}, FileNotFoundError("NoSuchBucket"), NO_SUCH_BUCKET_ERROR),
    ],
)
def test_validate_credentials(
    tmp_path: Path,
    files: dict[str, bytes],
    config_overrides: dict[str, str],
    fs_error: Exception | None,
    expected: str | None,
) -> None:
    for relative, content in files.items():
        write(tmp_path, relative, content)
    (tmp_path / "customer-data" / "exports").mkdir(parents=True, exist_ok=True)
    fs = _DeniedFileSystem(fs_error) if fs_error is not None else None
    source = _LocalAmazonS3Source(tmp_path, fs)

    valid, message = source.validate_credentials(make_config(**config_overrides), team_id=1)

    assert valid is (expected is None)
    if expected is not None:
        assert message is not None and message.startswith(expected)


@pytest.mark.parametrize(
    "sync_type, last_value, expected_files, expected_keys, mirrors",
    [
        (ExternalDataSchemaSyncType.FULL_REFRESH, None, ["a.csv", "b.csv", "c.csv"], None, False),
        (
            ExternalDataSchemaSyncType.INCREMENTAL,
            None,
            ["c.csv", "b.csv", "a.csv"],
            ["_file_name", "_file_row_number"],
            False,
        ),
        # The file at the watermark is read again, and the merge key replaces its rows.
        (
            ExternalDataSchemaSyncType.INCREMENTAL,
            FIRST_MODIFIED_AT + timedelta(minutes=1),
            ["b.csv", "a.csv"],
            ["_file_name", "_file_row_number"],
            False,
        ),
        # With the flag the run replaces the rows of the files it reads, so it needs no key.
        (
            ExternalDataSchemaSyncType.INCREMENTAL,
            FIRST_MODIFIED_AT + timedelta(minutes=1),
            ["b.csv", "a.csv"],
            None,
            True,
        ),
        # The pipeline can hand the watermark back without a timezone.
        (
            ExternalDataSchemaSyncType.INCREMENTAL,
            (FIRST_MODIFIED_AT + timedelta(minutes=2)).replace(tzinfo=None),
            ["a.csv"],
            ["_file_name", "_file_row_number"],
            False,
        ),
        # An append has no key, so the file at the watermark must not be read again.
        (ExternalDataSchemaSyncType.APPEND, FIRST_MODIFIED_AT + timedelta(minutes=1), ["a.csv"], None, False),
        (ExternalDataSchemaSyncType.APPEND, None, ["c.csv", "b.csv", "a.csv"], None, False),
        # The flag does not change an append.
        (ExternalDataSchemaSyncType.APPEND, FIRST_MODIFIED_AT + timedelta(minutes=1), ["a.csv"], None, True),
    ],
)
def test_sync_type_decides_which_files_are_read_and_whether_rows_merge(
    tmp_path: Path,
    sync_type: ExternalDataSchemaSyncType,
    last_value: datetime | None,
    expected_files: list[str],
    expected_keys: list[str] | None,
    mirrors: bool,
) -> None:
    # Path order is the reverse of age order, so the test tells the two apart.
    for minutes, name in enumerate(["c.csv", "b.csv", "a.csv"]):
        write(tmp_path, f"exports/orders/{name}", b"id\n1\n2\n", FIRST_MODIFIED_AT + timedelta(minutes=minutes))
    source = _LocalAmazonS3Source(tmp_path)
    config = make_config()
    [schema] = source.get_schemas(config, team_id=1)
    is_full_refresh = sync_type == ExternalDataSchemaSyncType.FULL_REFRESH
    inputs = source_inputs(
        schema.name,
        incremental_field=None if is_full_refresh else schema.incremental_fields[0]["field"],
        incremental_field_type=None if is_full_refresh else IncrementalFieldType.DateTime,
        db_incremental_field_last_value=last_value,
    )
    inputs.schema_metadata = schema.schema_metadata
    inputs.sync_type = sync_type
    inputs.source_cursor = SourceCursorManager.from_sync_type_config(source, {}, structlog.get_logger())

    with patch.object(source_base, "_mirrors_files", return_value=mirrors):
        response = source.source_for_pipeline(config, inputs)
        rows = [row for table in cast(Iterable[pa.Table], response.items()) for row in table.to_pylist()]

    assert [(row["_file_name"], row["_file_row_number"]) for row in rows] == [
        (f"orders/{name}", row_number) for name in expected_files for row_number in (0, 1)
    ]
    assert response.primary_keys == expected_keys
    mirrored = mirrors and sync_type == ExternalDataSchemaSyncType.INCREMENTAL
    assert response.replace_scope == (
        ReplaceScope(
            column="_file_name",
            replaced=frozenset(f"orders/{name}" for name in expected_files),
            retained=frozenset({"orders/a.csv", "orders/b.csv", "orders/c.csv"}),
        )
        if mirrored
        else None
    )


def test_a_mirrored_sync_of_a_bucket_that_did_not_change_reads_nothing(tmp_path: Path) -> None:
    for minutes, name in enumerate(["b.csv", "a.csv"]):
        write(tmp_path, f"exports/orders/{name}", b"id\n1\n", FIRST_MODIFIED_AT + timedelta(minutes=minutes))
    source = _LocalAmazonS3Source(tmp_path)
    config = make_config()
    [schema] = source.get_schemas(config, team_id=1)

    def sync(stored: dict[str, Any]) -> tuple[SourceResponse, int, SourceCursorManager]:
        inputs = source_inputs(
            schema.name,
            incremental_field=schema.incremental_fields[0]["field"],
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value=FIRST_MODIFIED_AT + timedelta(minutes=1),
        )
        inputs.schema_metadata = schema.schema_metadata
        inputs.sync_type = ExternalDataSchemaSyncType.INCREMENTAL
        cursor = SourceCursorManager.from_sync_type_config(source, stored, structlog.get_logger())
        inputs.source_cursor = cursor
        with patch.object(source_base, "_mirrors_files", return_value=True):
            response = source.source_for_pipeline(config, inputs)
            rows = sum(table.num_rows for table in cast(Iterable[pa.Table], response.items()))
        return response, rows, cursor

    first, first_rows, cursor = sync({})
    unchanged, unchanged_rows, _ = sync({"source_cursor": cursor.staged_payload()})
    write(tmp_path, "exports/orders/b.csv", b"id\n1\n2\n", FIRST_MODIFIED_AT + timedelta(minutes=2))
    rewritten, rewritten_rows, _ = sync({"source_cursor": cursor.staged_payload()})

    # The file at the watermark is read again on every run, so only the stored listing can tell
    # that nothing changed.
    assert (first.replace_scope is not None, first_rows) == (True, 1)
    assert (unchanged.replace_scope, unchanged_rows) == (None, 0)
    validate_incremental_sync(True, unchanged, is_first_sync=False)
    assert (rewritten.replace_scope is not None and rewritten.replace_scope.replaced, rewritten_rows) == (
        frozenset({"orders/a.csv", "orders/b.csv"}),
        3,
    )


@pytest.mark.parametrize(
    "sync_type, has_stored_cursor, mirrors, expected_ids, expected_columns, expected_reset",
    [
        (ExternalDataSchemaSyncType.APPEND, True, False, [2], {"id", "_delta_version"}, False),
        (ExternalDataSchemaSyncType.APPEND, False, False, [1, 2], {"id", "_delta_version"}, False),
        # A full refresh ignores the stored cursor, and still records the version it wrote.
        (ExternalDataSchemaSyncType.FULL_REFRESH, True, False, [1, 2], {"id"}, False),
        # An incremental sync names each row's data file, so the loader can replace rows by file.
        (ExternalDataSchemaSyncType.INCREMENTAL, True, True, [2], {"id", "_delta_version", "_file_name"}, False),
        # Without the flag the loader can't delete by file, so the run rebuilds the table.
        (ExternalDataSchemaSyncType.INCREMENTAL, True, False, [1, 2], {"id", "_delta_version", "_file_name"}, True),
    ],
)
def test_delta_sync_reads_from_the_stored_cursor_and_stages_the_next_one(
    tmp_path: Path,
    sync_type: ExternalDataSchemaSyncType,
    has_stored_cursor: bool,
    mirrors: bool,
    expected_ids: list[int],
    expected_columns: set[str],
    expected_reset: bool,
) -> None:
    table_path = str(tmp_path / "customer-data" / "exports" / "sales")
    write_deltalake(table_path, pa.table({"id": [1]}))
    source = _LocalAmazonS3Source(tmp_path)
    config = make_config()
    [schema] = source.get_schemas(config, team_id=1)
    reads_versions = sync_type != ExternalDataSchemaSyncType.FULL_REFRESH

    def sync(stored: dict[str, Any]) -> tuple[SourceResponse, list[dict[str, Any]], SourceCursorManager]:
        inputs = source_inputs(
            schema.name,
            incremental_field=schema.incremental_fields[0]["field"] if reads_versions else None,
            incremental_field_type=IncrementalFieldType.Integer if reads_versions else None,
        )
        inputs.schema_metadata = schema.schema_metadata
        inputs.sync_type = sync_type
        cursor = SourceCursorManager.from_sync_type_config(source, stored, structlog.get_logger())
        inputs.source_cursor = cursor
        with patch.object(source_base, "_mirrors_files", return_value=mirrors):
            response = source.source_for_pipeline(config, inputs)
            rows = [row for table in cast(Iterable[pa.Table], response.items()) for row in table.to_pylist()]
        return response, rows, cursor

    _, _, first_cursor = sync({})
    stored = {"source_cursor": first_cursor.staged_payload()} if has_stored_cursor else {}
    write_deltalake(table_path, pa.table({"id": [2]}), mode="append")
    response, rows, cursor = sync(stored)

    assert sorted(row["id"] for row in rows) == expected_ids
    assert all(set(row) == expected_columns for row in rows)
    assert response.destination_reset_required is expected_reset
    assert (response.replace_scope is not None) == (sync_type == ExternalDataSchemaSyncType.INCREMENTAL)
    staged = cursor.staged_payload()
    assert staged is not None and staged["data"]["version"] == 1
