from collections.abc import Iterable
from dataclasses import replace
from typing import Any, cast

import pytest
from unittest.mock import patch

from requests import HTTPError
from requests_mock import Mocker

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.turso import TursoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.turso.source import TursoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.turso.turso import get_resource

BASE_URL = "https://api.turso.tech"
ORG_URL = f"{BASE_URL}/v1/organizations/example-org"


@pytest.mark.parametrize(
    ("endpoint", "path", "row"),
    [
        ("databases", "/v1/organizations/example-org/databases", {"DbId": "db-1", "Name": "example-db"}),
        ("groups", "/v1/organizations/example-org/groups", {"uuid": "group-1", "name": "default"}),
        ("members", "/v1/organizations/example-org/members", {"username": "example-user", "role": "member"}),
        ("invites", "/v2/organizations/example-org/invites", {"id": 1, "created_at": "2026-01-01T00:00:00Z"}),
        ("invoices", "/v1/organizations/example-org/invoices?type=issued", {"invoice_number": "EXAMPLE-0001"}),
    ],
)
@pytest.mark.parametrize("empty", [False, True])
def test_unpaginated_lists_select_rows_and_use_bearer_auth(
    requests_mock: Mocker, config: TursoSourceConfig, endpoint: str, path: str, row: dict[str, Any], empty: bool
) -> None:
    rows = [] if empty else [row]
    requests_mock.get(BASE_URL + path, json={endpoint: rows}, complete_qs=True)
    assert list(get_resource(config, endpoint, 1, "test-job")) == ([] if empty else [rows])
    assert requests_mock.call_count == 1
    assert requests_mock.last_request is not None
    assert requests_mock.last_request.headers["Authorization"] == "Bearer test-platform-token"


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


@pytest.mark.parametrize("status", [429, 503])
def test_transient_errors_retry_through_the_framework(
    requests_mock: Mocker, config: TursoSourceConfig, status: int
) -> None:
    requests_mock.get(
        f"{ORG_URL}/databases",
        [
            {"status_code": status, "json": {"error": "Try again"}, "headers": {"Retry-After": "0"}},
            {"json": {"databases": [{"DbId": "db-1"}]}},
        ],
    )
    with patch("time.sleep"):
        assert list(get_resource(config, "databases", 1, "test-job")) == [[{"DbId": "db-1"}]]
    assert requests_mock.call_count == 2


def test_missing_envelope_is_not_a_successful_empty_sync(requests_mock: Mocker, config: TursoSourceConfig) -> None:
    requests_mock.get(f"{ORG_URL}/databases", json={"unexpected": []})
    with pytest.raises(ValueError, match="Required data_selector"):
        list(get_resource(config, "databases", 1, "test-job"))


@pytest.mark.parametrize("empty", [False, True])
def test_usage_fanout_preserves_database_identity_and_nested_metrics(
    requests_mock: Mocker, config: TursoSourceConfig, empty: bool
) -> None:
    databases = [] if empty else [{"DbId": "db-1", "Name": "example-db"}, {"DbId": "db-2", "Name": "other/db"}]
    requests_mock.get(f"{ORG_URL}/databases", json={"databases": databases}, complete_qs=True)
    usage = {"total": {"rows_read": 7, "rows_written": 3, "storage_bytes": 4096, "bytes_synced": 128}, "instances": []}
    requests_mock.get(f"{ORG_URL}/databases/example-db/usage", json={"database": usage}, complete_qs=True)
    requests_mock.get(f"{ORG_URL}/databases/other%2Fdb/usage", json={"database": usage}, complete_qs=True)
    rows = [row for page in get_resource(config, "database_usage", 1, "test-job") for row in page]
    assert rows == [dict(usage, database_id=db["DbId"], database_name=db["Name"]) for db in databases]
    assert requests_mock.call_count == 1 + len(databases)


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


def test_empty_audit_log_stops_on_first_page(
    requests_mock: Mocker, config: TursoSourceConfig, inputs: SourceInputs, resume_storage: None
) -> None:
    requests_mock.get(
        f"{ORG_URL}/audit-logs?page=1&page_size=100",
        json={"audit_logs": [], "pagination": {"total_pages": 0}},
        complete_qs=True,
    )
    source = TursoSource()
    inputs = replace(inputs, schema_name="audit_logs")
    manager = source.get_resumable_source_manager(inputs)
    response = source.source_for_pipeline(config, manager, inputs)
    assert list(cast(Iterable[list[dict[str, Any]]], response.items())) == []
    assert requests_mock.call_count == 1
    assert manager.has_staged_state() is False
