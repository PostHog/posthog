from collections.abc import Iterable
from dataclasses import replace
from typing import Any, cast

import pytest

from requests import HTTPError
from requests_mock import Mocker

from products.warehouse_sources.sources.sdk import SourceInputs
from products.warehouse_sources.sources.turso._config import TursoSourceConfig
from products.warehouse_sources.sources.turso.source import TursoSource
from products.warehouse_sources.sources.turso.turso import get_resource

BASE_URL = "https://api.turso.tech"
ORG_URL = f"{BASE_URL}/v1/organizations/example-org"


@pytest.mark.parametrize(
    ("status", "schema_name", "valid", "message_fragment"),
    [
        (200, None, True, None),
        (401, None, False, "invalid or expired"),
        (403, None, True, None),
        (403, "audit_logs", False, "Scaler"),
        (404, None, False, "organization slug"),
    ],
)
def test_credential_validation_distinguishes_tokens_from_table_permissions(
    requests_mock: Mocker,
    config: TursoSourceConfig,
    status: int,
    schema_name: str | None,
    valid: bool,
    message_fragment: str | None,
) -> None:
    path = "audit-logs" if schema_name else "databases"
    requests_mock.get(f"{ORG_URL}/{path}", status_code=status, json={"databases": []})
    result, message = TursoSource().validate_credentials(config, team_id=1, schema_name=schema_name)
    assert result is valid
    assert message is None if message_fragment is None else message is not None and message_fragment in message
    assert requests_mock.call_count == 1


@pytest.mark.parametrize("status", [401, 403, 400])
def test_sync_errors_are_classified_without_swallowing_them(
    requests_mock: Mocker, config: TursoSourceConfig, status: int
) -> None:
    requests_mock.get(f"{ORG_URL}/databases", status_code=status, json={"error": "Request rejected"})
    with pytest.raises(HTTPError) as error:
        list(get_resource(config, "databases", 1, "test-job"))
    assert requests_mock.call_count == 1
    terminal = any(pattern in str(error.value) for pattern in TursoSource().get_non_retryable_errors())
    assert terminal is (status in (401, 403))


def test_missing_envelope_is_not_a_successful_empty_sync(requests_mock: Mocker, config: TursoSourceConfig) -> None:
    requests_mock.get(f"{ORG_URL}/databases", json={"unexpected": []})
    with pytest.raises(ValueError, match="Required data_selector"):
        list(get_resource(config, "databases", 1, "test-job"))


USAGE = {"total": {"rows_read": 7, "rows_written": 3, "storage_bytes": 4096, "bytes_synced": 128}, "instances": []}
INSTANCES = [
    {
        "uuid": "inst-1",
        "name": "aws-us-east-1",
        "type": "primary",
        "region": "aws-us-east-1",
        "hostname": "a.example.com",
    },
    {
        "uuid": "inst-2",
        "name": "aws-eu-west-1",
        "type": "replica",
        "region": "aws-eu-west-1",
        "hostname": "b.example.com",
    },
]
TOP_QUERIES = [{"query": "SELECT 1", "rows_read": 1, "rows_written": 0}]


@pytest.mark.parametrize(
    ("endpoint", "suffix", "body", "expected"),
    [
        ("database_usage", "usage", {"database": USAGE}, [USAGE]),
        ("database_usage", "usage", None, []),
        ("database_instances", "instances", {"instances": INSTANCES}, INSTANCES),
        ("database_stats", "stats", {"top_queries": TOP_QUERIES}, TOP_QUERIES),
        ("database_stats", "stats", {"top_queries": None}, []),
    ],
)
def test_database_fanout_preserves_database_identity(
    requests_mock: Mocker,
    config: TursoSourceConfig,
    endpoint: str,
    suffix: str,
    body: dict[str, Any] | None,
    expected: list[dict[str, Any]],
) -> None:
    databases = [] if body is None else [{"DbId": "db-1", "Name": "example-db"}, {"DbId": "db-2", "Name": "other/db"}]
    requests_mock.get(f"{ORG_URL}/databases", json={"databases": databases}, complete_qs=True)
    requests_mock.get(f"{ORG_URL}/databases/example-db/{suffix}", json=body, complete_qs=True)
    requests_mock.get(f"{ORG_URL}/databases/other%2Fdb/{suffix}", json=body, complete_qs=True)
    rows = [row for page in get_resource(config, endpoint, 1, "test-job") for row in page]
    assert rows == [
        dict(item, database_id=db["DbId"], database_name=db["Name"]) for db in databases for item in expected
    ]
    assert requests_mock.call_count == 1 + len(databases)


def test_locations_map_becomes_one_row_per_code(requests_mock: Mocker, config: TursoSourceConfig) -> None:
    requests_mock.get(
        f"{BASE_URL}/v1/locations",
        json={"locations": {"aws-us-east-1": "AWS US East (Virginia)", "aws-eu-west-1": "AWS EU West (Ireland)"}},
    )
    rows = [row for page in get_resource(config, "locations", 1, "test-job") for row in page]
    assert rows == [
        {"code": "aws-us-east-1", "name": "AWS US East (Virginia)"},
        {"code": "aws-eu-west-1", "name": "AWS EU West (Ireland)"},
    ]


def test_audit_pages_restart_from_the_first_page(
    requests_mock: Mocker, config: TursoSourceConfig, inputs: SourceInputs, resume_storage: None
) -> None:
    inputs = replace(inputs, schema_name="audit_logs")
    source = TursoSource()
    manager = source.get_resumable_source_manager(inputs)
    first = {"code": "db-create", "created_at": "2026-01-02T00:00:00Z", "author": "example-user"}
    second = {"code": "group-create", "created_at": "2026-01-01T00:00:00Z", "author": "example-user"}
    requests_mock.get(
        f"{ORG_URL}/audit-logs?page=1&page_size=100",
        json={"audit_logs": [first], "pagination": {"total_pages": 2}},
        complete_qs=True,
    )
    requests_mock.get(
        f"{ORG_URL}/audit-logs?page=2&page_size=100",
        json={"audit_logs": [second], "pagination": {"total_pages": 2}},
        complete_qs=True,
    )
    response = source.source_for_pipeline(config, manager, inputs)
    assert list(cast(Iterable[list[dict[str, Any]]], response.items())) == [[first], [second]]
    assert manager.has_staged_state() is False

    restarted_manager = source.get_resumable_source_manager(inputs)
    restarted = source.source_for_pipeline(config, restarted_manager, inputs)
    assert list(cast(Iterable[list[dict[str, Any]]], restarted.items())) == [[first], [second]]
    assert [request.qs["page"] for request in requests_mock.request_history] == [["1"], ["2"], ["1"], ["2"]]
    assert response.supports_resume is False
    assert response.primary_keys is None
    assert response.partition_keys == ["created_at"]
    assert response.sort_mode == "desc"
