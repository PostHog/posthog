from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

import requests_mock
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mezmo import MezmoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mezmo.mezmo import MezmoResumeConfig, mezmo_source
from products.warehouse_sources.backend.temporal.data_imports.sources.mezmo.source import MezmoSource

BASE_URL = "https://api.mezmo.com/v3"


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


def rows(response: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in cast(Iterable[list[dict[str, Any]]], response.items()) for row in page]


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("account_id", [None, "example-account"])
@pytest.mark.parametrize("name", ["pipelines", "pipeline_health"])
def test_full_refresh_collections(manager: MagicMock, name: str, account_id: str | None, empty: bool) -> None:
    expected = [] if empty else [{"id": "pipeline-one", "title": "Example pipeline"}]
    path = "pipeline" if name == "pipelines" else "pipeline/health"
    body = {"data": expected} if name == "pipelines" else {"data": {"pipeline_health": {"pipelines": expected}}}
    config = MezmoSourceConfig(api_key="sts_example_key", account_id=account_id)
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/{path}", json=body, complete_qs=True)
        assert rows(mezmo_source(config, name, "v3", 1, "test-job", manager)) == expected
        assert http.call_count == 1
        request = http.request_history[0]
        assert request.headers["Authorization"] == "Token sts_example_key"
        assert request.headers.get("x-delegate-account-id") == account_id
        assert request.qs == {}
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("first_empty", [False, True])
def test_alerts_include_parent_key_and_finish_all_pipelines(manager: MagicMock, first_empty: bool) -> None:
    config = MezmoSourceConfig(api_key="sts_example_key")
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/pipeline", json={"data": [{"id": "one"}, {"id": "two"}]}, complete_qs=True)
        http.get(
            f"{BASE_URL}/pipeline/one/alert", json={"data": [] if first_empty else [{"id": "shared"}]}, complete_qs=True
        )
        http.get(f"{BASE_URL}/pipeline/two/alert", json={"data": [{"id": "shared"}]}, complete_qs=True)
        response = mezmo_source(config, "alerts", "v3", 1, "test-job", manager)
        expected = [] if first_empty else [{"id": "shared", "pipeline_id": "one"}]
        assert rows(response) == [*expected, {"id": "shared", "pipeline_id": "two"}]
        assert response.primary_keys == ["pipeline_id", "id"]
        assert http.call_count == 3
        for request in http.request_history:
            assert request.headers["Authorization"] == "Token sts_example_key"
            assert request.qs == {}
    manager.save_state.assert_called_with(
        MezmoResumeConfig(
            paginator_state={
                "completed": ["pipeline/one/alert", "pipeline/two/alert"],
                "current": None,
                "child_state": None,
            }
        )
    )
    manager.clear_state.assert_not_called()


def test_alert_resume_skips_completed_pipeline(manager: MagicMock) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = MezmoResumeConfig(
        paginator_state={"completed": ["pipeline/one/alert"], "current": "pipeline/two/alert", "child_state": None}
    )
    config = MezmoSourceConfig(api_key="sts_example_key")
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/pipeline", json={"data": [{"id": "one"}, {"id": "two"}]})
        http.get(f"{BASE_URL}/pipeline/two/alert", json={"data": [{"id": "alert-two"}]})
        assert rows(mezmo_source(config, "alerts", "v3", 1, "test-job", manager)) == [
            {"id": "alert-two", "pipeline_id": "two"}
        ]
        assert http.call_count == 2


@pytest.mark.parametrize("status", [401, 403])
def test_permanent_http_errors_match_source_messages(manager: MagicMock, status: int) -> None:
    config = MezmoSourceConfig(api_key="sts_example_key")
    with requests_mock.Mocker() as http:
        http.get(
            f"{BASE_URL}/pipeline",
            status_code=status,
            reason="Unauthorized" if status == 401 else "Forbidden",
            json={"message": "Unauthorized", "status": 401, "code": "EAUTH"}
            if status == 401
            else {"message": "Forbidden", "status": 403},
        )
        with pytest.raises(HTTPError) as exc:
            rows(mezmo_source(config, "pipelines", "v3", 1, "test-job", manager))
        assert error_message_matches(str(exc.value), MezmoSource().get_non_retryable_errors())
        assert http.call_count == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_errors_retry(manager: MagicMock, status: int) -> None:
    config = MezmoSourceConfig(api_key="sts_example_key")
    with requests_mock.Mocker() as http:
        http.get(
            f"{BASE_URL}/pipeline",
            [
                {"status_code": status, "json": {"message": "Try again"}, "headers": {"Retry-After": "0"}},
                {"json": {"data": [{"id": "one"}]}},
            ],
        )
        assert rows(mezmo_source(config, "pipelines", "v3", 1, "test-job", manager)) == [{"id": "one"}]
        assert http.call_count == 2


@pytest.mark.parametrize(
    "status, schema, valid", [(200, None, True), (401, None, False), (403, None, True), (403, "pipelines", False)]
)
def test_credential_probe(status: int, schema: str | None, valid: bool) -> None:
    config = MezmoSourceConfig(api_key="sts_example_key")
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/pipeline", status_code=status, json={"data": []})
        result, message = MezmoSource().validate_credentials(config, 1, schema)
        assert result is valid
        assert (message is None) is valid
        assert http.call_count == 1


@pytest.mark.parametrize(
    "schema, key, message",
    [("missing", "sts_example", "Unknown Mezmo table"), (None, "ste_example", "delegated account ID")],
)
def test_invalid_setup_does_not_request(schema: str | None, key: str, message: str) -> None:
    with requests_mock.Mocker() as http:
        valid, reason = MezmoSource().validate_credentials(MezmoSourceConfig(api_key=key), 1, schema)
        assert not valid
        assert reason is not None and message in reason
        assert http.call_count == 0


def test_health_probe_uses_health_endpoint() -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/pipeline/health", json={"data": {"pipeline_health": {"pipelines": []}}})
        assert MezmoSource().validate_credentials(MezmoSourceConfig(api_key="sts_example"), 1, "pipeline_health") == (
            True,
            None,
        )
        assert http.call_count == 1


def test_unknown_table_raises_before_request(manager: MagicMock) -> None:
    with requests_mock.Mocker() as http:
        with pytest.raises(UnknownResourceError):
            mezmo_source(MezmoSourceConfig(api_key="sts_example"), "missing", "v3", 1, "test-job", manager)
        assert http.call_count == 0


@pytest.mark.parametrize("body", [{}, {"message": "Unexpected response"}])
def test_missing_collection_fails_instead_of_erasing_table(manager: MagicMock, body: dict[str, Any]) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/pipeline", json=body)
        with pytest.raises(ValueError, match="Required data_selector"):
            rows(mezmo_source(MezmoSourceConfig(api_key="sts_example"), "pipelines", "v3", 1, "test-job", manager))
        assert http.call_count == 1


def test_alert_probe_checks_child_permissions() -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/pipeline", json={"data": [{"id": "one"}]})
        http.get(f"{BASE_URL}/pipeline/one/alert", status_code=403, json={"message": "Forbidden"})
        valid, message = MezmoSource().validate_credentials(MezmoSourceConfig(api_key="sts_example"), 1, "alerts")
        assert not valid
        assert message is not None and "read access" in message
        assert http.call_count == 2


def test_probe_preserves_unexpected_http_errors() -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/pipeline", status_code=404, json={"message": "Not found"})
        with pytest.raises(HTTPError):
            MezmoSource().validate_credentials(MezmoSourceConfig(api_key="sts_example"), 1)
        assert http.call_count == 1
