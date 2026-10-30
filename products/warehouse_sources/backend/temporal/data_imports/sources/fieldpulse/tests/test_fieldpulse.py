import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from time_machine import travel
from unittest.mock import MagicMock

import requests
import requests_mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fieldpulse.fieldpulse import (
    FieldpulseResumeConfig,
    fieldpulse_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fieldpulse.settings import AUTH_ERROR, BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.fieldpulse.source import FieldpulseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fieldpulse import (
    FieldpulseSourceConfig,
)


def driver() -> SourceDriver:
    return SourceDriver(FieldpulseSource(), FieldpulseSourceConfig(api_key="test-key"))


def items(source: Any) -> list[Any]:
    return list(cast(Iterable[Any], source.items()))


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


@pytest.mark.parametrize("endpoint", ["customers", "jobs", "estimates", "invoices", "payments", "projects"])
@pytest.mark.parametrize(
    "incremental,watermark,expected_filter",
    [
        (False, "2026-01-01T00:00:00+00:00", None),
        (True, None, None),
        (True, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        (True, datetime(2026, 1, 1, tzinfo=UTC), "2026-01-01T00:00:00+00:00"),
    ],
)
def test_requests_and_pagination(
    endpoint: str,
    incremental: bool,
    watermark: str | datetime | None,
    expected_filter: str | None,
) -> None:
    result = driver().run(
        endpoint,
        [
            ScriptedResponse(json={"error": False, "total_count": 2, "response": [{"id": 1}]}),
            ScriptedResponse(json={"error": False, "total_count": 2, "response": [{"id": 2}]}),
            ScriptedResponse(json={"error": False, "total_count": 2, "response": []}),
        ],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert result.items == [[{"id": 1}], [{"id": 2}]]
    assert result.params("page") == ["1", "2", "3"]
    for request in result.requests:
        assert request.headers["x-api-key"] == "test-key"
        assert request.param("limit") == "100"
        assert request.param("sort[0][attribute]") == ("updated_at" if incremental else "id")
        assert request.param("sort[0][order]") == "asc"
        if expected_filter is not None:
            assert request.param("filter[0][attribute]") == "updated_at"
            assert request.param("filter[0][operator]") == ">="
            assert request.param("filter[0][class]") == "date"
            assert request.param("filter[0][value]") == expected_filter
        else:
            assert not any(key.startswith("filter[") for key in request.query)
    assert result.response is not None
    assert result.response.sort_mode == ("asc" if incremental else None)
    assert result.saved_states == [
        FieldpulseResumeConfig(page=2, lower_bound=expected_filter),
        FieldpulseResumeConfig(page=3, lower_bound=expected_filter),
    ]


@pytest.mark.parametrize("endpoint", ["users", "job_status_workflows", "job_status_workflow_statuses", "timesheets"])
@pytest.mark.parametrize(
    "pages,expected_items,expected_pages",
    [
        pytest.param(
            [[{"id": 1}, {"id": 2}], [{"id": 1}, {"id": 2}]],
            [[{"id": 1}, {"id": 2}]],
            ["1", "2"],
            id="page_parameter_ignored",
        ),
        pytest.param(
            [[{"id": 1}], [{"id": 2}], []],
            [[{"id": 1}], [{"id": 2}]],
            ["1", "2", "3"],
            id="page_parameter_honored",
        ),
        pytest.param(
            [[{"id": 1}], [{"id": 2}], [{"id": 2}]],
            [[{"id": 1}], [{"id": 2}]],
            ["1", "2", "3"],
            id="last_page_repeats",
        ),
        pytest.param(
            [{"id": 1, "name": "Default"}, {"id": 1, "name": "Default"}],
            [[{"id": 1, "name": "Default"}]],
            ["1", "2"],
            id="single_record_response",
        ),
        pytest.param([[]], [], ["1"], id="no_rows"),
    ],
)
def test_endpoints_without_documented_paging_stop_on_a_repeated_page(
    endpoint: str,
    pages: list[Any],
    expected_items: list[list[dict[str, Any]]],
    expected_pages: list[str],
) -> None:
    result = driver().run(
        endpoint,
        [ScriptedResponse(json={"error": False, "response": page}) for page in pages],
    )

    assert result.raised is None
    assert result.items == expected_items
    assert result.params("page") == expected_pages
    for request in result.requests:
        assert request.param("sort[0][attribute]") == "id"
        assert not any(key.startswith("filter[") for key in request.query)


@pytest.mark.parametrize("saved_bound", [None, "2026-01-01T00:00:00+00:00"])
def test_resume_preserves_original_filter(saved_bound: str | None) -> None:
    result = driver().run(
        "customers",
        [ScriptedResponse(json={"error": False, "response": []})],
        resume_state=FieldpulseResumeConfig(page=3, lower_bound=saved_bound),
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-02-01T00:00:00+00:00",
    )

    assert result.raised is None
    assert result.items == []
    assert len(result.requests) == 1
    assert result.params("page") == ["3"]
    assert result.requests[0].param("filter[0][value]") == saved_bound
    assert result.saved_states == []


def test_expired_resume_state_starts_at_first_page(manager: MagicMock) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = None
    with requests_mock.Mocker() as http:
        http.get(BASE_URL + "customers", json={"error": False, "response": []})
        source = fieldpulse_source("test-key", "customers", 1, "job", manager, False, None)
        assert items(source) == []
        assert http.last_request is not None
        assert http.last_request.qs["page"] == ["1"]


@pytest.mark.parametrize("status", [422])
def test_authentication_errors(status: int) -> None:
    answer = ScriptedResponse(status=status, json={"message": "Invalid API key"})
    with scripted_network([answer]) as network:
        assert validate_credentials("test-key") == (False, AUTH_ERROR)

    assert len(network.requests_log) == 1
    assert network.requests_log[0].headers["x-api-key"] == "test-key"
    assert network.requests_log[0].query == {"limit": ("1",)}

    result = driver().run("customers", [answer])
    assert isinstance(result.raised, requests.HTTPError)
    assert len(result.requests) == 1
    mappings = FieldpulseSource().get_non_retryable_errors()
    assert any(pattern in str(result.raised) and message == AUTH_ERROR for pattern, message in mappings.items())


@pytest.mark.parametrize("rows", [[], [{"id": 1}]])
def test_valid_credentials_use_one_request(rows: list[dict[str, int]]) -> None:
    with scripted_network([ScriptedResponse(json={"error": False, "response": rows})]) as network:
        assert validate_credentials("test-key") == (True, None)

    assert len(network.requests_log) == 1


def test_other_client_errors_are_not_reported_as_bad_credentials() -> None:
    with scripted_network([ScriptedResponse(status=404, json={"message": "Request URL not found"})]) as network:
        with pytest.raises(requests.HTTPError):
            validate_credentials("test-key")

    assert len(network.requests_log) == 1


def test_missing_response_fails_instead_of_silently_importing_nothing() -> None:
    result = driver().run("customers", [ScriptedResponse(json={"error": True})])

    assert isinstance(result.raised, ValueError)
    assert "response" in str(result.raised)
    assert result.saved_states == []


@pytest.mark.parametrize("reset_value,expected_delay", [("1800000030", 30), ("invalid", 1), ("1799999990", 1)])
def test_vendor_rate_limit_reset(reset_value: str, expected_delay: int) -> None:
    request_times: list[float] = []

    def answer(_request: RecordedRequest) -> ScriptedResponse:
        request_times.append(time.monotonic())
        if len(request_times) == 1:
            return ScriptedResponse(status=429, json={"message": "Throttled"}, headers={"RateLimit-Reset": reset_value})
        return ScriptedResponse(json={"error": False, "response": []})

    with travel(datetime.fromtimestamp(1800000000, UTC), tick=False):
        result = driver().run("customers", answer)

    assert result.raised is None
    assert result.items == []
    assert len(result.requests) == 2
    assert request_times[1] - request_times[0] == pytest.approx(expected_delay, abs=0.1)
