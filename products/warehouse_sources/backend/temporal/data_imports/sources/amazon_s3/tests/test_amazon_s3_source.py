import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

import pytest

import pyarrow as pa
from fsspec import AbstractFileSystem
from fsspec.implementations.local import LocalFileSystem

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_s3.source import AmazonS3Source
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    ObjectStoreConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    ACCESS_DENIED_ERROR,
    INVALID_CONFIG_ERROR,
    NO_IMPORTABLE_FILES_ERROR,
    NO_SUCH_BUCKET_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem import ObjectStore
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import source_inputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amazons3 import (
    AmazonS3SourceConfig,
)


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

    def open_store(self, store_config: ObjectStoreConfig) -> ObjectStore:
        folder = self.root / store_config.bucket / store_config.prefix
        return ObjectStore(fs=self.fs, root=str(folder).rstrip("/"), delta_uri_prefix="", delta_storage_options={})


def make_config(**overrides: Any) -> AmazonS3SourceConfig:
    values: dict[str, Any] = {
        "bucket": "customer-data",
        "region": "us-east-1",
        "access_key_id": "AKIAEXAMPLE",
        "secret_access_key": "secret",
        "path": "exports",
        **overrides,
    }
    return AmazonS3SourceConfig.from_dict(values)


def write(root: Path, relative: str, content: bytes) -> None:
    path = root / "customer-data" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


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
        ({}, {"bucket": "Not A Bucket"}, None, INVALID_CONFIG_ERROR),
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
