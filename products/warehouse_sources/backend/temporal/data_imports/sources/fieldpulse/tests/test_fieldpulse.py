from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from time_machine import travel
from unittest.mock import MagicMock, patch

import requests
import requests_mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.fieldpulse.fieldpulse import (
    FieldpulseResumeConfig,
    fieldpulse_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fieldpulse.settings import AUTH_ERROR, BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.fieldpulse.source import FieldpulseSource


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
    manager: MagicMock,
    endpoint: str,
    incremental: bool,
    watermark: str | datetime | None,
    expected_filter: str | None,
) -> None:
    with requests_mock.Mocker() as http:
        http.get(
            BASE_URL + endpoint,
            [
                {"json": {"error": False, "total_count": 2, "response": [{"id": 1}]}},
                {"json": {"error": False, "total_count": 2, "response": [{"id": 2}]}},
                {"json": {"error": False, "total_count": 2, "response": []}},
            ],
        )
        source = fieldpulse_source("test-key", endpoint, 1, "job", manager, incremental, watermark)
        assert items(source) == [[{"id": 1}], [{"id": 2}]]
        assert [request.qs["page"] for request in http.request_history] == [["1"], ["2"], ["3"]]
        for request in http.request_history:
            assert request.headers["x-api-key"] == "test-key"
            assert request.qs["limit"] == ["100"]
            assert request.qs["sort[0][attribute]"] == ["updated_at" if incremental else "id"]
            assert request.qs["sort[0][order]"] == ["asc"]
            if expected_filter is not None:
                assert request.qs["filter[0][attribute]"] == ["updated_at"]
                assert request.qs["filter[0][operator]"] == [">="]
                assert request.qs["filter[0][class]"] == ["date"]
                assert request.qs["filter[0][value]"] == [expected_filter.lower()]
            else:
                assert not any(key.startswith("filter[") for key in request.qs)
        assert source.sort_mode == ("asc" if incremental else None)
        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            FieldpulseResumeConfig(page=2, lower_bound=expected_filter),
            FieldpulseResumeConfig(page=3, lower_bound=expected_filter),
        ]


@pytest.mark.parametrize("saved_bound", [None, "2026-01-01T00:00:00+00:00"])
def test_resume_preserves_original_filter(manager: MagicMock, saved_bound: str | None) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = FieldpulseResumeConfig(page=3, lower_bound=saved_bound)
    with requests_mock.Mocker() as http:
        http.get(BASE_URL + "customers", json={"error": False, "response": []})
        source = fieldpulse_source("test-key", "customers", 1, "job", manager, True, "2026-02-01T00:00:00+00:00")
        assert items(source) == []
        assert http.call_count == 1
        assert http.last_request is not None
        assert http.last_request.qs["page"] == ["3"]
        if saved_bound is None:
            assert "filter[0][value]" not in http.last_request.qs
        else:
            assert http.last_request.qs["filter[0][value]"] == [saved_bound.lower()]
        manager.save_state.assert_not_called()


def test_expired_resume_state_starts_at_first_page(manager: MagicMock) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = None
    with requests_mock.Mocker() as http:
        http.get(BASE_URL + "customers", json={"error": False, "response": []})
        source = fieldpulse_source("test-key", "customers", 1, "job", manager, False, None)
        assert items(source) == []
        assert http.last_request is not None
        assert http.last_request.qs["page"] == ["1"]


@pytest.mark.parametrize("status", [401, 403, 422])
def test_authentication_errors(manager: MagicMock, status: int) -> None:
    with requests_mock.Mocker() as http:
        http.get(BASE_URL + "customers", status_code=status, json={"message": "Invalid API key"})
        assert validate_credentials("test-key") == (False, AUTH_ERROR)
        assert http.call_count == 1
        assert http.last_request is not None
        assert http.last_request.headers["x-api-key"] == "test-key"
        assert http.last_request.qs == {"limit": ["1"]}
        source = fieldpulse_source("test-key", "customers", 1, "job", manager, False, None)
        with pytest.raises(requests.HTTPError) as error:
            items(source)
        assert http.call_count == 2
        mappings = FieldpulseSource().get_non_retryable_errors()
        assert any(pattern in str(error.value) and message == AUTH_ERROR for pattern, message in mappings.items())


@pytest.mark.parametrize("rows", [[], [{"id": 1}]])
def test_valid_credentials_use_one_request(rows: list[dict[str, int]]) -> None:
    with requests_mock.Mocker() as http:
        http.get(BASE_URL + "customers", json={"error": False, "response": rows})
        assert validate_credentials("test-key") == (True, None)
        assert http.call_count == 1


def test_other_client_errors_are_not_reported_as_bad_credentials() -> None:
    with requests_mock.Mocker() as http:
        http.get(BASE_URL + "customers", status_code=404, json={"message": "Request URL not found"})
        with pytest.raises(requests.HTTPError):
            validate_credentials("test-key")
        assert http.call_count == 1


def test_missing_response_fails_instead_of_silently_importing_nothing(manager: MagicMock) -> None:
    with requests_mock.Mocker() as http:
        http.get(BASE_URL + "customers", json={"error": True})
        source = fieldpulse_source("test-key", "customers", 1, "job", manager, False, None)
        with pytest.raises(ValueError, match="response"):
            items(source)
        manager.save_state.assert_not_called()


def test_unknown_table_is_rejected_before_request(manager: MagicMock) -> None:
    with requests_mock.Mocker() as http:
        with pytest.raises(UnknownResourceError):
            fieldpulse_source("test-key", "unknown", 1, "job", manager, False, None)
        assert http.call_count == 0


@pytest.mark.parametrize("reset_value,expected_delay", [("1800000030", 30), ("invalid", 1), ("1799999990", 1)])
def test_vendor_rate_limit_reset(manager: MagicMock, reset_value: str, expected_delay: int) -> None:
    with travel(datetime.fromtimestamp(1800000000, UTC), tick=False), requests_mock.Mocker() as http:
        http.get(
            BASE_URL + "customers",
            [
                {"status_code": 429, "json": {"message": "Throttled"}, "headers": {"RateLimit-Reset": reset_value}},
                {"json": {"error": False, "response": []}},
            ],
        )
        with patch("tenacity.nap.time.sleep") as sleep:
            source = fieldpulse_source("test-key", "customers", 1, "job", manager, False, None)
            assert items(source) == []
        sleep.assert_called_once_with(expected_delay)
        assert http.call_count == 2
