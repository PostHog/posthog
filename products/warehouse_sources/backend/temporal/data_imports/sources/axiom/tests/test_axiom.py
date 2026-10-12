from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

import structlog
from requests.exceptions import HTTPError
from requests_mock import Mocker

from products.warehouse_sources.backend.temporal.data_imports.sources.axiom.axiom import AxiomResumeConfig, axiom_source
from products.warehouse_sources.backend.temporal.data_imports.sources.axiom.source import AxiomSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.axiom import AxiomSourceConfig


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


def make_inputs(table: str) -> SourceInputs:
    return SourceInputs(
        schema_name=table,
        schema_id="schema-test",
        source_id="source-test",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value="2025-01-01T00:00:00Z",
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-test",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


@pytest.mark.parametrize("table", ["datasets", "monitors", "annotations"])
@pytest.mark.parametrize("rows", [[], [{"id": "record-1"}, {"id": "record-2"}]])
@pytest.mark.parametrize("org_id", [None, "example-org"])
def test_single_page_full_refresh(
    requests_mock: Mocker, manager: MagicMock, table: str, rows: list[dict[str, str]], org_id: str | None
) -> None:
    endpoint = requests_mock.get(f"https://api.axiom.co/v2/{table}", json=rows)
    response = axiom_source(AxiomSourceConfig(api_token="test-token", org_id=org_id), make_inputs(table), manager)

    pages = cast(Iterable[list[dict[str, str]]], response.items())
    assert [row for page in pages for row in page] == rows
    assert endpoint.call_count == 1
    request = endpoint.last_request
    assert request is not None
    assert request.headers["Authorization"] == "Bearer test-token"
    assert request.headers.get("x-axiom-org-id") == org_id
    assert request.qs == {}
    assert request.body is None
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("table,path", [("dashboards", "dashboards"), ("saved_queries", "apl-starred-queries")])
@pytest.mark.parametrize("terminal_page", [[], [{"id": "last-record"}]])
def test_offset_pages_stop_and_save_next_offset(
    requests_mock: Mocker, manager: MagicMock, table: str, path: str, terminal_page: list[dict[str, str]]
) -> None:
    first_page = [{"id": f"record-{index}"} for index in range(100)]
    endpoint = requests_mock.get(f"https://api.axiom.co/v2/{path}", [{"json": first_page}, {"json": terminal_page}])
    response = axiom_source(AxiomSourceConfig(api_token="test-token"), make_inputs(table), manager)

    pages = cast(Iterable[list[dict[str, str]]], response.items())
    assert [row for page in pages for row in page] == first_page + terminal_page
    assert endpoint.call_count == 2
    extra_params = {"who": ["all"]} if table == "saved_queries" else {}
    assert [request.qs for request in endpoint.request_history] == [
        {"offset": ["0"], "limit": ["100"], **extra_params},
        {"offset": ["100"], "limit": ["100"], **extra_params},
    ]
    assert all(request.headers["Authorization"] == "Bearer test-token" for request in endpoint.request_history)
    manager.save_state.assert_called_once_with(AxiomResumeConfig(offset=100))


@pytest.mark.parametrize("saved_offset", [None, 200])
def test_resume_uses_saved_offset(requests_mock: Mocker, manager: MagicMock, saved_offset: int | None) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = None if saved_offset is None else AxiomResumeConfig(offset=saved_offset)
    endpoint = requests_mock.get("https://api.axiom.co/v2/dashboards", json=[{"id": "last-record"}])
    response = axiom_source(AxiomSourceConfig(api_token="test-token"), make_inputs("dashboards"), manager)

    pages = cast(Iterable[list[dict[str, str]]], response.items())
    assert [row for page in pages for row in page] == [{"id": "last-record"}]
    assert endpoint.last_request is not None
    assert endpoint.last_request.qs["offset"] == [str(saved_offset or 0)]
    manager.save_state.assert_not_called()
    assert response.on_complete is not None
    response.on_complete()
    manager.clear_state.assert_called_once_with()


@pytest.mark.parametrize("org_id", [None, "example-org"])
def test_credentials_use_one_request(requests_mock: Mocker, org_id: str | None) -> None:
    endpoint = requests_mock.get("https://api.axiom.co/v2/datasets", json=[])

    assert AxiomSource().validate_credentials(AxiomSourceConfig(api_token="test-token", org_id=org_id), 1) == (
        True,
        None,
    )
    assert endpoint.call_count == 1
    assert endpoint.last_request is not None
    assert endpoint.last_request.headers["Authorization"] == "Bearer test-token"
    assert endpoint.last_request.headers.get("x-axiom-org-id") == org_id


def test_credentials_fall_back_to_an_authorized_resource(requests_mock: Mocker) -> None:
    datasets = requests_mock.get("https://api.axiom.co/v2/datasets", status_code=403)
    monitors = requests_mock.get("https://api.axiom.co/v2/monitors", status_code=403)
    annotations = requests_mock.get("https://api.axiom.co/v2/annotations", json=[])

    assert AxiomSource().validate_credentials(AxiomSourceConfig(api_token="test-token"), 1) == (True, None)
    assert datasets.call_count == monitors.call_count == annotations.call_count == 1


def test_credentials_use_selected_resource(requests_mock: Mocker) -> None:
    endpoint = requests_mock.get("https://api.axiom.co/v2/dashboards", json=[])

    assert AxiomSource().validate_credentials(AxiomSourceConfig(api_token="test-token"), 1, "dashboards") == (
        True,
        None,
    )
    assert endpoint.last_request is not None
    assert endpoint.last_request.qs == {"limit": ["1"]}


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (401, {"code": 401, "message": "auth token not provided"}, "Axiom rejected the token"),
        (403, {"code": 403, "message": "Forbidden"}, "Axiom denied access"),
    ],
)
def test_auth_errors_match_validation_and_pipeline(
    requests_mock: Mocker, manager: MagicMock, status: int, body: dict[str, Any], expected: str
) -> None:
    endpoint = requests_mock.get("https://api.axiom.co/v2/datasets", status_code=status, json=body)
    source = AxiomSource()
    config = AxiomSourceConfig(api_token="test-token")

    valid, message = source.validate_credentials(config, 1, "datasets")
    assert valid is False
    assert message is not None and message.startswith(expected)
    with pytest.raises(HTTPError) as raised:
        list(cast(Iterable[Any], axiom_source(config, make_inputs("datasets"), manager).items()))
    assert endpoint.call_count == 2
    matching_messages = [
        mapped for pattern, mapped in source.get_non_retryable_errors().items() if pattern in str(raised.value)
    ]
    assert matching_messages == [message]
    assert "test-token" not in str(raised.value)


@pytest.mark.parametrize(
    "status,exception", [(404, HTTPError), (429, RESTClientRetryableError), (503, RESTClientRetryableError)]
)
def test_probe_preserves_non_auth_failures(requests_mock: Mocker, status: int, exception: type[Exception]) -> None:
    endpoint = requests_mock.get("https://api.axiom.co/v2/datasets", status_code=status, json={"code": status})

    with pytest.raises(exception):
        AxiomSource().validate_credentials(AxiomSourceConfig(api_token="test-token"), 1)
    assert endpoint.call_count == 1


def test_unknown_table_fails_before_request(requests_mock: Mocker, manager: MagicMock) -> None:
    with pytest.raises(UnknownResourceError, match="unknown_table"):
        axiom_source(AxiomSourceConfig(api_token="test-token"), make_inputs("unknown_table"), manager)
    assert requests_mock.call_count == 0


@pytest.mark.parametrize("body", [{"message": "Unexpected response"}, None])
def test_unexpected_response_is_not_imported_as_a_record(
    requests_mock: Mocker, manager: MagicMock, body: dict[str, str] | None
) -> None:
    requests_mock.get("https://api.axiom.co/v2/datasets", json=body)
    config = AxiomSourceConfig(api_token="test-token")

    with pytest.raises(ValueError, match="Required a list response body"):
        list(cast(Iterable[Any], axiom_source(config, make_inputs("datasets"), manager).items()))
    with pytest.raises(ValueError, match="Required a list response body"):
        AxiomSource().validate_credentials(config, 1)
