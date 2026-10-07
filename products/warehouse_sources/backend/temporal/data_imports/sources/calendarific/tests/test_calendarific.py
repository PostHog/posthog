from collections.abc import Iterable, Iterator
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

import responses
from requests import HTTPError, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.calendarific.calendarific import (
    CalendarificClient,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.calendarific.source import CalendarificSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.calendarific import (
    CalendarificSourceConfig,
)

BASE_URL = "https://calendarific.com/api/v2"
API_KEY = "calendarific-test-key"


@pytest.fixture
def http() -> Iterator[responses.RequestsMock]:
    with (
        Session() as session,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
            return_value=session,
        ),
        responses.RequestsMock() as mocked,
    ):
        yield mocked


def client(country: str = " us ", year: str = " 2026 ") -> CalendarificClient:
    return CalendarificClient(CalendarificSourceConfig(api_key=API_KEY, country=country, year=year), "v2")


@pytest.mark.parametrize("endpoint", ["holidays", "countries", "languages"])
@pytest.mark.parametrize("empty", [False, True])
def test_full_refresh_reads_one_complete_response(http: responses.RequestsMock, endpoint: str, empty: bool) -> None:
    rows = [] if empty else [{"name": "Example record"}, {"name": "Another example record"}]
    http.get(f"{BASE_URL}/{endpoint}", json={"meta": {"code": 200}, "response": {endpoint: rows}})

    result = client().source_response(endpoint, 1, "test-job")
    pages = cast(Iterable[Iterable[Any]], result.items())
    assert [row for page in pages for row in page] == rows
    assert len(http.calls) == 1
    request = http.calls[0].request
    assert request.method == "GET"
    assert "Authorization" not in request.headers
    expected = {"api_key": [API_KEY]}
    if endpoint == "holidays":
        expected.update({"country": ["US"], "year": ["2026"]})
    assert parse_qs(urlsplit(request.url).query) == expected


@pytest.mark.parametrize("schema_name", [None, "holidays", "countries", "languages"])
def test_credential_probe_uses_one_request(http: responses.RequestsMock, schema_name: str | None) -> None:
    endpoint = schema_name or "holidays"
    http.get(f"{BASE_URL}/{endpoint}", json={"meta": {"code": 200}, "response": {endpoint: []}})

    assert client().validate_credentials(1, schema_name) == (True, None)
    assert len(http.calls) == 1
    expected = {"api_key": [API_KEY]}
    if endpoint == "holidays":
        expected.update({"country": ["US"], "year": ["2026"], "month": ["1"], "day": ["1"]})
    assert parse_qs(urlsplit(http.calls[0].request.url).query) == expected


@pytest.mark.parametrize(
    ("country", "year", "schema_name", "message"),
    [
        ("USA", "2026", None, "two-letter country code"),
        ("", "2026", None, "two-letter country code"),
        ("U1", "2026", None, "two-letter country code"),
        ("US", "26", None, "four-digit year"),
        ("US", "2026.5", None, "four-digit year"),
        ("US", "0000", None, "four-digit year"),
        ("US", "", None, "four-digit year"),
        ("US", "2026", "unknown", "Unknown Calendarific table"),
    ],
)
def test_invalid_configuration_makes_no_request(
    http: responses.RequestsMock, country: str, year: str, schema_name: str | None, message: str
) -> None:
    transport = client(country, year)
    valid, error = transport.validate_credentials(1, schema_name)
    assert not valid
    assert error is not None and message in error
    with pytest.raises(ValueError, match=message):
        transport.source_response(schema_name or "holidays", 1, "test-job")
    assert len(http.calls) == 0


@pytest.mark.parametrize(
    ("status", "error_type", "message"),
    [
        (401, "auth failed", "Copy the key from your Calendarific dashboard"),
        (403, "subscription_expired", "Renew it in your Calendarific account"),
    ],
)
def test_authentication_errors_are_actionable_and_terminal(
    http: responses.RequestsMock, status: int, error_type: str, message: str
) -> None:
    http.get(
        f"{BASE_URL}/holidays",
        status=status,
        json={"meta": {"code": status, "error_type": error_type}, "response": []},
    )
    valid, error = client().validate_credentials(1, None)
    assert not valid
    assert error is not None and message in error
    assert len(http.calls) == 1

    with pytest.raises(HTTPError) as raised:
        list(cast(Iterable[Any], client().source_response("holidays", 1, "test-job").items()))
    assert API_KEY not in str(raised.value)
    mappings = CalendarificSource().get_non_retryable_errors()
    assert any(pattern in str(raised.value) and mapped == error for pattern, mapped in mappings.items())
    assert len(http.calls) == 2


@pytest.mark.parametrize("status", [400, 404])
def test_other_http_errors_are_not_reported_as_invalid_credentials(http: responses.RequestsMock, status: int) -> None:
    http.get(f"{BASE_URL}/holidays", status=status, json={"meta": {"code": status}, "response": []})
    with pytest.raises(HTTPError):
        client().validate_credentials(1, None)
    assert len(http.calls) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_errors_use_framework_retries(http: responses.RequestsMock, status: int) -> None:
    http.get(f"{BASE_URL}/holidays", status=status, json={"meta": {"code": status}, "response": []})
    http.get(f"{BASE_URL}/holidays", json={"meta": {"code": 200}, "response": {"holidays": []}})
    with patch.object(RESTClient._send_request.retry, "sleep", return_value=None):  # type: ignore[attr-defined]
        assert client().validate_credentials(1, None) == (True, None)
    assert len(http.calls) == 2


@pytest.mark.parametrize("endpoint", ["holidays", "countries", "languages"])
def test_missing_collection_fails_instead_of_erasing_table(http: responses.RequestsMock, endpoint: str) -> None:
    http.get(f"{BASE_URL}/{endpoint}", json={"meta": {"code": 200}, "response": {"unexpected": []}})
    with pytest.raises(ValueError, match="matched nothing"):
        list(cast(Iterable[Any], client().source_response(endpoint, 1, "test-job").items()))
    assert len(http.calls) == 1


def test_source_delegates_with_resolved_version() -> None:
    config = CalendarificSourceConfig(api_key=API_KEY, country="US", year="2026")
    inputs = MagicMock(spec=SourceInputs)
    inputs.api_version = "v2"
    inputs.schema_name = "holidays"
    inputs.team_id = 1
    inputs.job_id = "test-job"
    expected = MagicMock()

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.calendarific.source.CalendarificClient"
    ) as client_class:
        client_class.return_value.source_response.return_value = expected
        result = CalendarificSource().source_for_pipeline(config, inputs)

    assert result is expected
    client_class.assert_called_once_with(config, "v2")
    client_class.return_value.source_response.assert_called_once_with("holidays", 1, "test-job")


def test_source_delegates_credential_validation_with_resolved_version() -> None:
    config = CalendarificSourceConfig(api_key=API_KEY, country="US", year="2026")

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.calendarific.source.CalendarificClient"
    ) as client_class:
        client_class.return_value.validate_credentials.return_value = (True, None)
        result = CalendarificSource().validate_credentials(config, 1, "holidays", "v2")

    assert result == (True, None)
    client_class.assert_called_once_with(config, "v2")
    client_class.return_value.validate_credentials.assert_called_once_with(1, "holidays")
