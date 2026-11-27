import io
import time
import struct
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest

import pyarrow as pa
import fastavro
import pyarrow.parquet as pq

from products.warehouse_sources.sources.r2_data_catalog import r2_data_catalog
from products.warehouse_sources.sources.r2_data_catalog._config import R2DataCatalogSourceConfig
from products.warehouse_sources.sources.r2_data_catalog.r2_data_catalog import (
    FILE_TOO_LARGE_MESSAGE,
    INCREMENTAL_COLUMN_MISSING_MESSAGE,
    INVALID_ACCOUNT_MESSAGE,
    INVALID_BUCKET_MESSAGE,
    INVALID_TOKEN_MESSAGE,
    INVALID_URI_MESSAGE,
    INVALID_WATERMARK_MESSAGE,
    NO_CREDENTIALS_MESSAGE,
    NOT_FOUND_MESSAGE,
    PERMISSION_MESSAGE,
    STORAGE_PERMISSION_MESSAGE,
    TABLE_NOT_FOUND_MESSAGE,
    UNSUPPORTED_DELETES_MESSAGE,
    DataFile,
    IcebergColumn,
    IncrementalFilter,
    R2DataCatalogResumeConfig,
    TableIdentifier,
    align_to_schema,
    file_may_match,
    normalize_catalog_uri,
    parse_table,
)
from products.warehouse_sources.sources.r2_data_catalog.source import R2DataCatalogSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network

CATALOG_URI = "https://catalog.cloudflarestorage.com/acct123/lake"
STORAGE_HOST = "acct123.r2.cloudflarestorage.com"
PREFIX = "acct123_lake"
TABLE_PATH = f"/v1/{PREFIX}/namespaces/analytics/tables/events"
LOCATION = "s3://lake/__r2_data_catalog/events"

MANIFEST_LIST_SCHEMA = {
    "type": "record",
    "name": "manifest_file",
    "fields": [
        {"name": "manifest_path", "type": "string"},
        {"name": "content", "type": "int"},
    ],
}
BOUND = {
    "type": "record",
    "name": "k_v",
    "fields": [{"name": "key", "type": "int"}, {"name": "value", "type": "bytes"}],
}
MANIFEST_SCHEMA = {
    "type": "record",
    "name": "manifest_entry",
    "fields": [
        {"name": "status", "type": "int"},
        {
            "name": "data_file",
            "type": {
                "type": "record",
                "name": "r2",
                "fields": [
                    {"name": "content", "type": "int"},
                    {"name": "file_path", "type": "string"},
                    {"name": "file_format", "type": "string"},
                    {"name": "record_count", "type": "long"},
                    {"name": "upper_bounds", "type": ["null", {"type": "array", "items": BOUND}]},
                ],
            },
        },
    ],
}

# Field 1 `id` (long), field 2 `name` (string, renamed from `title`), field 3 `ts` (timestamptz),
# field 4 `day` (date) and field 5 `score` (double, added after the first file was written).
SCHEMA_FIELDS = [
    {"id": 1, "name": "id", "type": "long", "required": True},
    {"id": 2, "name": "name", "type": "string", "required": False},
    {"id": 3, "name": "ts", "type": "timestamptz", "required": False},
    {"id": 4, "name": "day", "type": "date", "required": False},
    {"id": 5, "name": "score", "type": "double", "required": False},
]


def _avro(schema: dict[str, Any], records: list[dict[str, Any]]) -> bytes:
    buffer = io.BytesIO()
    fastavro.writer(buffer, fastavro.parse_schema(schema), records)
    return buffer.getvalue()


def _field(name: str, arrow_type: pa.DataType, field_id: int) -> pa.Field:
    return pa.field(name, arrow_type, metadata={b"PARQUET:field_id": str(field_id).encode()})


def _parquet(table: pa.Table) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


def _old_file(ids: list[int]) -> bytes:
    # Written before `title` became `name` and before `score` existed.
    schema = pa.schema(
        [
            _field("id", pa.int64(), 1),
            _field("title", pa.string(), 2),
            _field("ts", pa.timestamp("us", tz="UTC"), 3),
            _field("day", pa.date32(), 4),
        ]
    )
    return _parquet(
        pa.table(
            {
                "id": ids,
                "title": [f"row {i}" for i in ids],
                "ts": [datetime(2024, 1, i, tzinfo=UTC) for i in ids],
                "day": [date(2024, 1, i) for i in ids],
            },
            schema=schema,
        )
    )


def _new_file(ids: list[int]) -> bytes:
    schema = pa.schema(
        [
            _field("id", pa.int64(), 1),
            _field("name", pa.string(), 2),
            _field("ts", pa.timestamp("us", tz="UTC"), 3),
            _field("day", pa.date32(), 4),
            _field("score", pa.float64(), 5),
        ]
    )
    return _parquet(
        pa.table(
            {
                "id": ids,
                "name": [f"row {i}" for i in ids],
                "ts": [datetime(2024, 1, i, tzinfo=UTC) for i in ids],
                "day": [date(2024, 1, i) for i in ids],
                "score": [float(i) for i in ids],
            },
            schema=schema,
        )
    )


def _upper_bounds(max_id: int) -> list[dict[str, Any]]:
    micros = int((datetime(2024, 1, max_id, tzinfo=UTC) - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds()) * 10**6
    days = (date(2024, 1, max_id) - date(1970, 1, 1)).days
    return [
        {"key": 1, "value": struct.pack("<q", max_id)},
        {"key": 3, "value": struct.pack("<q", micros)},
        {"key": 4, "value": struct.pack("<i", days)},
    ]


def _data_entry(path: str, count: int, max_id: int, content: int = 0) -> dict[str, Any]:
    return {
        "status": 1,
        "data_file": {
            "content": content,
            "file_path": path,
            "file_format": "PARQUET",
            "record_count": count,
            "upper_bounds": _upper_bounds(max_id) if content == 0 else None,
        },
    }


class FakeR2:
    """An R2 Data Catalog with one table, `analytics.events`, and the R2 bucket that holds its files."""

    def __init__(
        self,
        with_deletes: bool = True,
        extra_entries: list[dict[str, Any]] | None = None,
        delete_positions: dict[str, list[int]] | None = None,
    ) -> None:
        self.files: dict[str, bytes] = {
            "/lake/data/a.parquet": _old_file([1, 2, 3]),
            "/lake/data/b.parquet": _new_file([4, 5, 6]),
        }
        entries = [
            # Listed out of path order: the source reads files in path order.
            _data_entry("s3://lake/data/b.parquet", 3, 6),
            _data_entry("s3://lake/data/a.parquet", 3, 3),
            {**_data_entry("s3://lake/data/gone.parquet", 3, 9), "status": 2},
        ]
        if with_deletes:
            positions = delete_positions or {"s3://lake/data/a.parquet": [1]}
            self.files["/lake/data/del.parquet"] = _parquet(
                pa.table(
                    {
                        "file_path": [path for path, rows in positions.items() for _ in rows],
                        "pos": pa.array([row for rows in positions.values() for row in rows], type=pa.int64()),
                    }
                )
            )
            entries.append(_data_entry("s3://lake/data/del.parquet", 1, 0, content=1))
        entries.extend(extra_entries or [])
        self.files["/lake/meta/m1.avro"] = _avro(MANIFEST_SCHEMA, entries)
        self.files["/lake/meta/list.avro"] = _avro(
            MANIFEST_LIST_SCHEMA, [{"manifest_path": "s3://lake/meta/m1.avro", "content": 0}]
        )
        self.metadata: dict[str, Any] = {
            "format-version": 2,
            "location": LOCATION,
            "current-schema-id": 1,
            "schemas": [
                {"schema-id": 0, "fields": SCHEMA_FIELDS[:4]},
                {"schema-id": 1, "fields": SCHEMA_FIELDS, "identifier-field-ids": [1]},
            ],
            "current-snapshot-id": 7,
            "snapshots": [
                {"snapshot-id": 7, "manifest-list": "s3://lake/meta/list.avro", "summary": {"total-records": "5"}}
            ],
        }
        self.credentials: dict[str, str] = {
            "s3.access-key-id": "AKIDVENDED",
            "s3.secret-access-key": "vended-secret",
            "s3.session-token": "vended-session",
            "s3.endpoint": f"https://{STORAGE_HOST}",
        }
        self.storage_status = 200
        # Storage answers 403 to this many requests first, as R2 does for vended credentials that expired.
        self.expired_answers = 0

    def __call__(self, request: Any) -> ScriptedResponse:
        if request.origin.endswith(STORAGE_HOST):
            if self.expired_answers:
                self.expired_answers -= 1
                return ScriptedResponse(status=403, body=b"<Error><Code>AccessDenied</Code></Error>")
            if self.storage_status != 200:
                return ScriptedResponse(status=self.storage_status, body=b"<Error><Code>AccessDenied</Code></Error>")
            return ScriptedResponse(body=self.files[request.path])
        if request.path == "/acct123/lake/v1/config":
            return ScriptedResponse(json={"defaults": {}, "overrides": {"prefix": PREFIX}})
        if request.path == f"/acct123/lake/v1/{PREFIX}/namespaces":
            if request.param("pageToken") is None:
                return ScriptedResponse(json={"namespaces": [["analytics"]], "next-page-token": "p2"})
            return ScriptedResponse(json={"namespaces": [["staging"]]})
        if request.path == f"/acct123/lake/v1/{PREFIX}/namespaces/analytics/tables":
            return ScriptedResponse(json={"identifiers": [{"namespace": ["analytics"], "name": "events"}]})
        if request.path == f"/acct123/lake/v1/{PREFIX}/namespaces/staging/tables":
            return ScriptedResponse(json={"identifiers": []})
        if request.path == f"/acct123/lake{TABLE_PATH}":
            body: dict[str, Any] = {"metadata-location": f"{LOCATION}/metadata/v1.json", "metadata": self.metadata}
            if request.headers.get("x-iceberg-access-delegation") == "vended-credentials":
                body["config"] = self.credentials
            return ScriptedResponse(json=body)
        return ScriptedResponse(status=404, json={"error": {"message": "not found", "type": "NoSuchTableException"}})


def _driver() -> SourceDriver:
    return SourceDriver(
        R2DataCatalogSource(),
        R2DataCatalogSourceConfig(account_id="acct123", bucket_name="lake", api_token="cf-token"),
    )


def _rows(result: Any) -> list[dict[str, Any]]:
    return [row for item in result.items for row in item.to_pylist()]


def _ids(result: Any) -> list[int]:
    return [row["id"] for row in _rows(result)]


def _storage_paths(result: Any) -> list[str]:
    return [request.path for request in result.requests if request.origin.endswith(STORAGE_HOST)]


def test_full_refresh_reads_files_in_path_order_by_field_id_and_drops_deleted_rows() -> None:
    result = _driver().run("analytics.events", FakeR2())

    assert result.raised is None
    # Row position 1 of a.parquet (id 2) is deleted by the position delete file.
    assert _ids(result) == [1, 3, 4, 5, 6]
    rows = _rows(result)
    first, last = rows[0], rows[-1]
    # `title` in the old file is field 2, which the current schema calls `name`.
    assert first["name"] == "row 1"
    assert first["score"] is None
    assert last["score"] == 6.0
    assert result.response is not None
    assert result.response.primary_keys == ["id"]
    assert result.response.sort_mode is None
    # The removed entry (status 2) is never downloaded.
    assert "/lake/data/gone.parquet" not in _storage_paths(result)
    # The table loads directly by its name, with no walk over the catalog's namespaces.
    assert not any(r.path.endswith("/namespaces") for r in result.requests)

    catalog_requests = [r for r in result.requests if not r.origin.endswith(STORAGE_HOST)]
    assert all(r.headers["authorization"] == "Bearer cf-token" for r in catalog_requests)
    storage_requests = [r for r in result.requests if r.origin.endswith(STORAGE_HOST)]
    assert all(
        r.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDVENDED/") for r in storage_requests
    )
    assert all(r.headers["x-amz-security-token"] == "vended-session" for r in storage_requests)
    # Load-table answers carry vended storage keys, so the catalog session must stay out of HTTP sample capture.
    catalog_sessions = [o for o in result.session_options if "Authorization" in (o.get("headers") or {})]
    assert catalog_sessions and all(o.get("capture") is False for o in catalog_sessions)


@pytest.mark.parametrize(
    ("field", "last_value", "should_use", "expected_ids"),
    [
        ("id", 5, True, [5, 6]),
        ("ts", datetime(2024, 1, 5, tzinfo=UTC), True, [5, 6]),
        ("ts", "2024-01-05T00:00:00Z", True, [5, 6]),
        ("day", date(2024, 1, 5), True, [5, 6]),
        ("id", 3, True, [3, 4, 5, 6]),
        # A full refresh on a schema with an incremental field reads every row.
        ("id", 5, False, [1, 3, 4, 5, 6]),
    ],
)
def test_incremental_skips_files_below_the_watermark_and_filters_rows(
    field: str, last_value: Any, should_use: bool, expected_ids: list[int]
) -> None:
    result = _driver().run(
        "analytics.events",
        FakeR2(),
        incremental_field=field,
        db_incremental_field_last_value=last_value,
        should_use_incremental_field=should_use,
    )

    assert result.raised is None
    assert _ids(result) == expected_ids
    assert ("/lake/data/a.parquet" in _storage_paths(result)) is (1 in expected_ids or 3 in expected_ids)


def test_state_is_staged_before_each_batch_and_points_past_finished_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r2_data_catalog, "BATCH_ROWS", 2)

    result = _driver().run("analytics.events", FakeR2(with_deletes=False))

    assert _ids(result) == [1, 2, 3, 4, 5, 6]
    assert result.saved_states == [
        R2DataCatalogResumeConfig(snapshot_id=7, file_index=0, rows_done=2),
        R2DataCatalogResumeConfig(snapshot_id=7, file_index=1, rows_done=0),
        R2DataCatalogResumeConfig(snapshot_id=7, file_index=1, rows_done=2),
        R2DataCatalogResumeConfig(snapshot_id=7, file_index=2, rows_done=0),
    ]


@pytest.mark.parametrize(
    ("resume_state", "incremental", "expected_ids", "reads_first_file", "resets"),
    [
        (R2DataCatalogResumeConfig(snapshot_id=7, file_index=1, rows_done=1), False, [5, 6], False, False),
        (R2DataCatalogResumeConfig(snapshot_id=7, file_index=0, rows_done=2), False, [3, 4, 5, 6], True, False),
        # A snapshot that has expired since the last attempt starts the read again. A full refresh then resets
        # the destination, or the rows the earlier attempt loaded would be appended twice.
        (R2DataCatalogResumeConfig(snapshot_id=3, file_index=1, rows_done=1), False, [1, 2, 3, 4, 5, 6], True, True),
        # An incremental read merges on the key, so reading rows again needs no reset.
        (R2DataCatalogResumeConfig(snapshot_id=3, file_index=1, rows_done=1), True, [1, 2, 3, 4, 5, 6], True, False),
    ],
)
def test_resume_continues_inside_the_saved_file(
    resume_state: R2DataCatalogResumeConfig,
    incremental: bool,
    expected_ids: list[int],
    reads_first_file: bool,
    resets: bool,
) -> None:
    result = _driver().run(
        "analytics.events",
        FakeR2(with_deletes=False),
        resume_state=resume_state,
        incremental_field="id" if incremental else None,
        db_incremental_field_last_value=None,
    )

    assert result.raised is None
    assert _ids(result) == expected_ids
    assert ("/lake/data/a.parquet" in _storage_paths(result)) is reads_first_file
    assert result.response is not None
    assert result.response.destination_reset_required is resets


def test_a_file_removed_in_any_manifest_is_not_read() -> None:
    fake = FakeR2(with_deletes=False, extra_entries=[{**_data_entry("s3://lake/data/a.parquet", 3, 3), "status": 2}])

    result = _driver().run("analytics.events", fake)

    assert _ids(result) == [4, 5, 6]
    assert "/lake/data/a.parquet" not in _storage_paths(result)


def test_position_deletes_apply_per_file_across_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r2_data_catalog, "BATCH_ROWS", 2)
    fake = FakeR2(delete_positions={"s3://lake/data/a.parquet": [2, 0], "s3://lake/data/b.parquet": [1]})

    result = _driver().run("analytics.events", fake)

    assert _ids(result) == [2, 4, 6]


def test_a_file_larger_than_the_cap_raises_a_non_retryable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r2_data_catalog, "MAX_DATA_FILE_BYTES", 100)

    result = _driver().run("analytics.events", FakeR2(with_deletes=False))

    assert str(result.raised) == FILE_TOO_LARGE_MESSAGE
    assert FILE_TOO_LARGE_MESSAGE in R2DataCatalogSource().get_non_retryable_errors()


def test_table_without_a_snapshot_yields_an_empty_table_with_the_schema() -> None:
    fake = FakeR2()
    fake.metadata["current-snapshot-id"] = -1

    result = _driver().run("analytics.events", fake)

    assert result.raised is None
    assert _rows(result) == []
    assert result.items[0].column_names == ["id", "name", "ts", "day", "score"]
    assert _storage_paths(result) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda fake: setattr(fake, "storage_status", 403), STORAGE_PERMISSION_MESSAGE),
        (lambda fake: setattr(fake, "credentials", {}), NO_CREDENTIALS_MESSAGE),
        (
            lambda fake: fake.credentials.update({"s3.endpoint": "https://attacker.example.com"}),
            "storage endpoint outside Cloudflare R2",
        ),
    ],
)
def test_storage_failures_raise_a_clear_error(change: Callable[[FakeR2], None], expected: str) -> None:
    fake = FakeR2()
    change(fake)

    result = _driver().run("analytics.events", fake)

    assert result.raised is not None
    assert expected in str(result.raised)


def test_storage_403_gets_new_credentials_and_retries_once() -> None:
    fake = FakeR2(with_deletes=False)
    fake.expired_answers = 1

    result = _driver().run("analytics.events", fake)

    assert result.raised is None
    assert _ids(result) == [1, 2, 3, 4, 5, 6]
    vend_requests = [r for r in result.requests if r.headers.get("x-iceberg-access-delegation")]
    assert len(vend_requests) == 2


@pytest.mark.parametrize(
    ("field", "last_value", "expected"),
    [
        ("ts", "not a time", INVALID_WATERMARK_MESSAGE),
        # A cursor column renamed or retyped in Iceberg is gone by its stored name.
        ("renamed_ts", "2024-01-05", INCREMENTAL_COLUMN_MISSING_MESSAGE),
        ("name", "row 5", INCREMENTAL_COLUMN_MISSING_MESSAGE),
    ],
)
def test_unusable_incremental_settings_raise_a_non_retryable_error(field: str, last_value: str, expected: str) -> None:
    result = _driver().run(
        "analytics.events", FakeR2(), incremental_field=field, db_incremental_field_last_value=last_value
    )

    assert str(result.raised) == expected
    assert expected in R2DataCatalogSource().get_non_retryable_errors()


STRUCT_TYPE = {
    "type": "struct",
    "fields": [
        {"id": 11, "name": "city", "type": "string", "required": False},
        {"id": 12, "name": "zip", "type": "string", "required": False},
    ],
}


def test_schema_alignment_fills_columns_the_file_does_not_hold() -> None:
    # Written without field ids, as an imported Parquet file is: `old_name` is field 1 by the name mapping.
    address = pa.array([{"town": "Paris", "zip": "75001"}])
    file_table = pa.table(
        {"old_name": pa.array([7], type=pa.int64()), "address": address},
    )
    columns = [
        IcebergColumn(field_id=1, name="id", type="long", required=True),
        IcebergColumn(field_id=2, name="region", type="string", required=False),
        IcebergColumn(field_id=3, name="flag", type="boolean", required=False, initial_default=True),
        IcebergColumn(field_id=4, name="day", type="date", required=False, initial_default="2024-01-02"),
        IcebergColumn(field_id=5, name="missing", type="int", required=False),
        IcebergColumn(field_id=6, name="address", type=STRUCT_TYPE, required=False),
    ]

    aligned = align_to_schema(file_table, columns, name_mapping={1: frozenset({"old_name"})}, constants={2: "eu-west"})

    assert aligned.to_pylist() == [
        {
            "id": 7,
            "region": "eu-west",
            "flag": True,
            "day": date(2024, 1, 2),
            "missing": None,
            # `town` was renamed to `city` in the current schema; without field ids it can't be matched.
            "address": {"city": None, "zip": "75001"},
        }
    ]


def test_nested_struct_children_follow_their_field_ids() -> None:
    children = pa.struct(
        [
            pa.field("town", pa.string(), metadata={b"PARQUET:field_id": b"11"}),
            pa.field("dropped", pa.string(), metadata={b"PARQUET:field_id": b"13"}),
        ]
    )
    file_table = pa.table(
        [pa.array([{"town": "Paris", "dropped": "x"}, None], type=children)],
        schema=pa.schema([pa.field("address", children, metadata={b"PARQUET:field_id": b"6"})]),
    )

    aligned = align_to_schema(file_table, [IcebergColumn(field_id=6, name="address", type=STRUCT_TYPE, required=False)])

    assert aligned.to_pylist() == [{"address": {"city": "Paris", "zip": None}}, {"address": None}]


def test_columns_from_files_before_a_type_promotion_get_the_current_type() -> None:
    old = pa.table(
        [pa.array([2**31 - 1], type=pa.int32()), pa.array([1.5], type=pa.float32())],
        schema=pa.schema([_field("id", pa.int32(), 1), _field("score", pa.float32(), 5)]),
    )
    columns = [
        IcebergColumn(field_id=1, name="id", type="long", required=True),
        IcebergColumn(field_id=5, name="score", type="double", required=False),
    ]

    aligned = align_to_schema(old, columns)

    assert aligned.schema.types == [pa.int64(), pa.float64()]
    assert aligned.to_pylist() == [{"id": 2**31 - 1, "score": 1.5}]


@pytest.mark.parametrize(
    ("type_name", "bound", "matches"),
    [
        ("long", struct.pack("<q", 4), False),
        ("long", struct.pack("<q", 5), True),
        # An int column promoted to long keeps the 4-byte bounds of its old files.
        ("long", struct.pack("<i", 4), False),
        ("timestamptz", struct.pack("<q", 4), False),
        # A date promoted to a timestamp keeps 4-byte day bounds, which are not in microseconds.
        ("timestamptz", struct.pack("<i", 4), True),
        ("date", struct.pack("<i", 4), False),
    ],
)
def test_file_pruning_only_trusts_bounds_in_the_column_unit(type_name: str, bound: bytes, matches: bool) -> None:
    row_filter = IncrementalFilter(
        column=IcebergColumn(field_id=9, name="c", type=type_name, required=False), threshold=5
    )

    assert file_may_match(DataFile(path="f", record_count=1, upper_bounds={9: bound}), row_filter) is matches


def test_equality_deletes_are_refused() -> None:
    fake = FakeR2(extra_entries=[_data_entry("s3://lake/data/eq.parquet", 1, 0, content=2)])

    result = _driver().run("analytics.events", fake)

    assert result.raised is not None
    assert str(result.raised) == UNSUPPORTED_DELETES_MESSAGE
    assert _rows(result) == []


def test_unknown_table_raises_table_not_found() -> None:
    result = _driver().run("analytics.missing", FakeR2())

    assert str(result.raised) == f"{TABLE_NOT_FOUND_MESSAGE} Table: analytics.missing"


def test_vended_credentials_are_renewed_before_they_expire() -> None:
    fake = FakeR2(with_deletes=False)
    fake.credentials["s3.session-token-expires-at-ms"] = str(int((time.time() + 60) * 1000))

    result = _driver().run("analytics.events", fake)

    assert result.raised is None
    vend_requests = [r for r in result.requests if r.headers.get("x-iceberg-access-delegation")]
    # The credentials expire inside the refresh margin, so every storage read asks for new ones.
    assert len(vend_requests) == len(_storage_paths(result))


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, INVALID_TOKEN_MESSAGE),
        (403, PERMISSION_MESSAGE),
        (404, NOT_FOUND_MESSAGE),
    ],
)
def test_validate_credentials_maps_catalog_errors(status: int, expected: str) -> None:
    config = R2DataCatalogSourceConfig(account_id="acct123", bucket_name="lake", api_token="bad")
    answer = ScriptedResponse(
        status=status, json={"error": {"message": "Unauthorized", "type": "NotAuthorizedException", "code": status}}
    )

    with scripted_network([answer]):
        assert R2DataCatalogSource().validate_credentials(config, team_id=1) == (False, expected)


@pytest.mark.parametrize(
    ("account_id", "bucket_name", "catalog_uri", "expected"),
    [
        ("acct123", "lake", "https://evil.example.com/a/b", INVALID_URI_MESSAGE),
        ("acct123/../other", "lake", None, INVALID_ACCOUNT_MESSAGE),
        ("acct123", "lake/../../v1", None, INVALID_BUCKET_MESSAGE),
    ],
)
def test_validate_credentials_rejects_bad_locations_without_a_request(
    account_id: str, bucket_name: str, catalog_uri: str | None, expected: str
) -> None:
    config = R2DataCatalogSourceConfig(
        account_id=account_id, bucket_name=bucket_name, api_token="t", catalog_uri=catalog_uri
    )

    with scripted_network([]) as network:
        assert R2DataCatalogSource().validate_credentials(config, team_id=1) == (False, expected)
    assert network.requests_log == []


def test_catalog_uri_override_replaces_the_default_catalog() -> None:
    config = R2DataCatalogSourceConfig(
        account_id="acct123",
        bucket_name="lake",
        api_token="t",
        catalog_uri="https://eu.catalog.cloudflarestorage.com/acct123/lake",
    )

    with scripted_network([ScriptedResponse(json={}), ScriptedResponse(json={"namespaces": []})]) as network:
        assert R2DataCatalogSource().validate_credentials(config, team_id=1) == (True, None)
    assert [r.url for r in network.requests_log] == [
        "https://eu.catalog.cloudflarestorage.com/acct123/lake/v1/config?warehouse=acct123_lake",
        "https://eu.catalog.cloudflarestorage.com/acct123/lake/v1/namespaces",
    ]


@pytest.mark.parametrize(
    ("names", "lists_namespaces"),
    [
        (None, True),
        # Named tables load directly, so a table past the discovery cap is still found.
        (["analytics.events", "analytics.missing"], True),
        (["analytics.events"], False),
    ],
)
def test_get_schemas_lists_tables_across_namespace_pages(names: list[str] | None, lists_namespaces: bool) -> None:
    config = R2DataCatalogSourceConfig(account_id="acct123", bucket_name="lake", api_token="cf-token")

    with scripted_network(FakeR2()) as network:
        schemas = R2DataCatalogSource().get_schemas(config, team_id=1, with_counts=True, names=names)

    assert any(r.path.endswith("/namespaces") for r in network.requests_log) is lists_namespaces
    assert len(schemas) == 1
    schema = schemas[0]
    assert schema.name == "analytics.events"
    assert schema.detected_primary_keys == ["id"]
    assert schema.row_count == 5
    assert [field["field"] for field in schema.incremental_fields] == ["id", "ts", "day"]
    assert schema.columns[1] == ("name", "string", True)


def test_discovery_stops_walking_namespaces_at_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r2_data_catalog, "MAX_DISCOVERED_NAMESPACES", 1)
    config = R2DataCatalogSourceConfig(account_id="acct123", bucket_name="lake", api_token="cf-token")

    with scripted_network(FakeR2()) as network:
        schemas = R2DataCatalogSource().get_schemas(config, team_id=1)

    assert [schema.name for schema in schemas] == ["analytics.events"]
    # The second page of namespaces is never requested.
    assert not any(r.param("pageToken") for r in network.requests_log)


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        ({"total-records": "5"}, 5),
        # Position deletes are counted apart from the data files and removed at read time.
        ({"total-records": "5", "total-position-deletes": "2"}, 3),
        ({"total-records": "5", "total-equality-deletes": "1"}, None),
        ({}, None),
    ],
)
def test_row_count_leaves_out_deleted_rows(summary: dict[str, str], expected: int | None) -> None:
    metadata = {**FakeR2().metadata, "snapshots": [{"snapshot-id": 7, "summary": summary}]}

    table = parse_table(TableIdentifier(namespace=("analytics",), name="events"), {"metadata": metadata})

    assert table.total_records == expected


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (CATALOG_URI, CATALOG_URI),
        (f" {CATALOG_URI}/ ", CATALOG_URI),
        ("https://eu.catalog.cloudflarestorage.com/acct/lake", "https://eu.catalog.cloudflarestorage.com/acct/lake"),
        ("http://catalog.cloudflarestorage.com/acct/lake", None),
        ("https://catalog.cloudflarestorage.com.evil.com/acct/lake", None),
        ("https://evilcloudflarestorage.com/acct/lake", None),
        # A backslash makes the HTTP client send the request to the host before it.
        ("https://attacker.example\\catalog.cloudflarestorage.com/acct/lake", None),
        ("https://catalog.cloudflarestorage.com/acct\\@attacker.example/lake", None),
        ("https://user:pw@catalog.cloudflarestorage.com/acct/lake", None),
        ("https://catalog.cloudflarestorage.com:8443/acct/lake", None),
        ("https://catalog.cloudflarestorage.com/", None),
        ("https://catalog.cloudflarestorage.com/acct/lake?x=1", None),
    ],
)
def test_normalize_catalog_uri_only_accepts_cloudflare_hosts(uri: str, expected: str | None) -> None:
    if expected is None:
        with pytest.raises(ValueError, match="catalog URI"):
            normalize_catalog_uri(uri)
    else:
        assert normalize_catalog_uri(uri) == expected
