from collections.abc import AsyncIterable
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import pyarrow as pa
import structlog
import pyarrow.parquet as pq
from fsspec.implementations.local import LocalFileSystem

from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    INVALID_CONFIG_ERROR,
    NO_TABLE_FILES_ERROR,
    ObjectStorageError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.source import FileUploadSource

UPLOAD_ID = "11111111-2222-4333-8444-555555555555"
OTHER_UPLOAD_ID = "99999999-2222-4333-8444-555555555555"
TEAM_ID = 7


def _inputs(schema_metadata: dict[str, Any] | None = None) -> SourceInputs:
    return SourceInputs(
        schema_name="orders",
        schema_id="schema",
        source_id="source",
        team_id=TEAM_ID,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job",
        logger=structlog.get_logger(),
        reset_pipeline=False,
        schema_metadata=schema_metadata,
    )


def _job_inputs(**overrides: str) -> dict[str, str]:
    return {
        "upload_id": UPLOAD_ID,
        "filename": "orders.csv",
        "file_format": "csv",
        "schema_name": "orders",
        **overrides,
    }


def _write(bucket: Path, key: str, content: bytes) -> None:
    path = bucket / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _read(job_inputs: dict[str, str], schema_metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    source = FileUploadSource()
    response = source.source_for_pipeline(source.parse_config(job_inputs), _inputs(schema_metadata))
    items = response.items()
    assert not isinstance(items, (pa.Table, AsyncIterable))
    return [row for table in items for row in table.to_pylist()]


@pytest.fixture
def bucket(tmp_path: Path) -> Any:
    root = (tmp_path / "ph-warehouse").resolve()
    root.mkdir()
    # Files the source must never read: another upload of the team, another team, the bucket root.
    _write(root, f"file_uploads/team_{TEAM_ID}/{OTHER_UPLOAD_ID}/orders.csv", b"id\nother-upload\n")
    _write(root, f"file_uploads/team_8/{UPLOAD_ID}/orders.csv", b"id\nother-team\n")
    _write(root, "orders.csv", b"id\nbucket-root\n")
    with (
        override_settings(DATAWAREHOUSE_BUCKET=str(root)),
        patch.object(source_module, "get_s3_client", return_value=LocalFileSystem()) as get_s3_client,
    ):
        yield root, get_s3_client


def test_reads_only_the_upload_its_inputs_name(bucket: Any) -> None:
    root, _ = bucket
    _write(root, f"file_uploads/team_{TEAM_ID}/{UPLOAD_ID}/orders.csv", b"id,total\n1,9\n2,11\n")

    rows = _read(_job_inputs())

    assert [(row["id"], row["total"]) for row in rows] == [("1", "9"), ("2", "11")]
    assert {row["_file_name"] for row in rows} == {"orders.csv"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"upload_id": f"../team_8/{UPLOAD_ID}"},
        {"upload_id": ".."},
        {"upload_id": "/"},
        {"upload_id": "other-bucket"},
        {"upload_id": f"{UPLOAD_ID}/../{OTHER_UPLOAD_ID}"},
        {"filename": "../../team_8/" + UPLOAD_ID + "/orders.csv"},
        {"filename": "../" + OTHER_UPLOAD_ID + "/orders.csv"},
        {"filename": "/etc/passwd"},
        {"filename": ".."},
        {"filename": ""},
    ],
)
def test_crafted_inputs_never_reach_storage(bucket: Any, overrides: dict[str, str]) -> None:
    _, get_s3_client = bucket

    with pytest.raises(ObjectStorageError, match=INVALID_CONFIG_ERROR):
        _read(_job_inputs(**overrides))

    get_s3_client.assert_not_called()


def test_a_missing_upload_fails_without_reading_another_file(bucket: Any) -> None:
    with pytest.raises(ObjectStorageError, match=NO_TABLE_FILES_ERROR):
        _read(_job_inputs())


def test_an_unknown_file_format_is_refused(bucket: Any) -> None:
    with pytest.raises(ObjectStorageError, match=INVALID_CONFIG_ERROR):
        _read(_job_inputs(file_format="xlsx"))


@pytest.mark.parametrize(
    "schema_metadata, expected_total, expected_preserve",
    [
        (None, "9", False),
        ({"csv": {"has_header": True, "allow_double_quotes": True, "column_types": {"total": "integer"}}}, 9, False),
        ({"csv": {"has_header": True, "allow_double_quotes": True}, "preserve_column_names": True}, "9", True),
        # A path in the schema is never where the file is read from.
        ({"kind": "files", "scope": "file", "path": "../../orders.csv", "format": "csv", "csv": {}}, "9", False),
    ],
)
def test_read_options_come_from_the_schema_and_the_path_from_the_inputs(
    bucket: Any, schema_metadata: dict[str, Any] | None, expected_total: Any, expected_preserve: bool
) -> None:
    root, _ = bucket
    _write(root, f"file_uploads/team_{TEAM_ID}/{UPLOAD_ID}/orders.csv", b"id,total\n1,9\n")
    source = FileUploadSource()

    response = source.source_for_pipeline(source.parse_config(_job_inputs()), _inputs(schema_metadata))
    items = response.items()
    assert not isinstance(items, (pa.Table, AsyncIterable))
    [row] = [row for table in items for row in table.to_pylist()]

    assert row["total"] == expected_total
    assert response.preserve_column_names is expected_preserve
    assert response.primary_keys is None


@pytest.mark.parametrize(
    "file_format, filename, content, expected",
    [
        ("json", "events.json", b'{"id": 1}\n{"id": 2}\n', [1, 2]),
        ("parquet", "events.parquet", None, [1, 2]),
        # A name discovery would treat as hidden still reads, because the upload names the file.
        ("csv", "_events.csv", b"id\n1\n2\n", ["1", "2"]),
    ],
)
def test_every_upload_format_reads(
    bucket: Any, tmp_path: Path, file_format: str, filename: str, content: bytes | None, expected: list[Any]
) -> None:
    root, _ = bucket
    if content is None:
        parquet_path = tmp_path / "events.parquet"
        pq.write_table(pa.table({"id": [1, 2]}), parquet_path)
        content = parquet_path.read_bytes()
    _write(root, f"file_uploads/team_{TEAM_ID}/{UPLOAD_ID}/{filename}", content)

    rows = _read(_job_inputs(filename=filename, file_format=file_format))

    assert [row["id"] for row in rows] == expected


@pytest.mark.parametrize(
    "exists, expected",
    [(True, (True, None)), (False, (False, "The uploaded file wasn't found. Upload the file again."))],
)
def test_validate_credentials_checks_the_upload_exists(bucket: Any, exists: bool, expected: tuple) -> None:
    root, _ = bucket
    if exists:
        _write(root, f"file_uploads/team_{TEAM_ID}/{UPLOAD_ID}/orders.csv", b"id\n1\n")
    source = FileUploadSource()

    assert source.validate_credentials(source.parse_config(_job_inputs()), TEAM_ID) == expected


@pytest.mark.parametrize("names, expected", [(None, ["orders"]), (["orders"], ["orders"]), (["refunds"], [])])
def test_discovery_returns_only_the_sources_own_schema(names: list[str] | None, expected: list[str]) -> None:
    source = FileUploadSource()

    schemas = source.get_schemas(source.parse_config(_job_inputs()), TEAM_ID, names=names)

    assert [schema.name for schema in schemas] == expected
    assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)


def test_the_upload_inputs_are_server_managed() -> None:
    assert set(FileUploadSource().server_managed_job_input_fields({}, {})) == {
        "upload_id",
        "filename",
        "file_format",
        "schema_name",
    }


def test_cleanup_runs_only_while_a_replaced_upload_waits() -> None:
    source = FileUploadSource()
    waiting = MagicMock(
        team_id=TEAM_ID,
        connection_metadata={
            "file_upload": {
                "superseded": [
                    {"upload_id": UPLOAD_ID, "filename": "a.csv", "superseded_at": "2026-01-01T00:00:00+00:00"}
                ]
            }
        },
    )
    idle = MagicMock(team_id=TEAM_ID, connection_metadata={"file_upload": {"superseded": []}})
    # An entry that can't name one of the team's uploads is never deleted, so it schedules nothing.
    unparseable = MagicMock(
        team_id=TEAM_ID,
        connection_metadata={"file_upload": {"superseded": [{"upload_id": "../x", "filename": "a.csv"}]}},
    )

    assert source.has_cleanup_after_sync(waiting) is True
    assert source.has_cleanup_after_sync(idle) is False
    assert source.has_cleanup_after_sync(unparseable) is False
