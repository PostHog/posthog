import pytest
from unittest.mock import MagicMock, patch

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.calendarific.calendarific import (
    CalendarificClient,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.calendarific.source import CalendarificSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.calendarific import (
    CalendarificSourceConfig,
)

BASE_URL = "https://calendarific.com/api/v2"
API_KEY = "calendarific-test-key"


def client(country: str = " us ", year: str = " 2026 ") -> CalendarificClient:
    return CalendarificClient(CalendarificSourceConfig(api_key=API_KEY, country=country, year=year), "v2")


def driver() -> SourceDriver:
    return SourceDriver(CalendarificSource(), CalendarificSourceConfig(api_key=API_KEY, country=" us ", year=" 2026 "))


@pytest.mark.parametrize("schema_name", [None, "holidays", "countries", "languages"])
def test_credential_probe_uses_one_request(schema_name: str | None) -> None:
    endpoint = schema_name or "holidays"
    with scripted_network([ScriptedResponse(json={"meta": {"code": 200}, "response": {endpoint: []}})]) as network:
        assert client().validate_credentials(1, schema_name) == (True, None)

    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.url.startswith(f"{BASE_URL}/{endpoint}?")
    expected = {"api_key": (API_KEY,)}
    if endpoint == "holidays":
        expected.update({"country": ("US",), "year": ("2026",), "month": ("1",), "day": ("1",)})
    assert request.query == expected


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
def test_invalid_configuration_makes_no_request(country: str, year: str, schema_name: str | None, message: str) -> None:
    transport = client(country, year)
    with scripted_network([]) as network:
        valid, error = transport.validate_credentials(1, schema_name)
        assert not valid
        assert error is not None and message in error
        with pytest.raises(ValueError, match=message):
            transport.source_response(schema_name or "holidays", 1, "test-job")
    assert network.requests_log == []


@pytest.mark.parametrize(
    ("status", "error_type", "message"),
    [
        (401, "auth failed", "Copy the key from your Calendarific dashboard"),
        (403, "subscription_expired", "Renew it in your Calendarific account"),
    ],
)
def test_authentication_errors_are_actionable_and_terminal(status: int, error_type: str, message: str) -> None:
    answer = ScriptedResponse(status=status, json={"meta": {"code": status, "error_type": error_type}, "response": []})
    with scripted_network([answer]) as network:
        valid, error = client().validate_credentials(1, None)
    assert not valid
    assert error is not None and message in error
    assert len(network.requests_log) == 1

    result = driver().run("holidays", [answer])
    assert isinstance(result.raised, HTTPError)
    assert API_KEY not in str(result.raised)
    mappings = CalendarificSource().get_non_retryable_errors()
    assert any(pattern in str(result.raised) and mapped == error for pattern, mapped in mappings.items())
    assert len(result.requests) == 1


@pytest.mark.parametrize("status", [400, 404])
def test_other_http_errors_are_not_reported_as_invalid_credentials(status: int) -> None:
    answer = ScriptedResponse(status=status, json={"meta": {"code": status}, "response": []})
    with scripted_network([answer]) as network:
        with pytest.raises(HTTPError):
            client().validate_credentials(1, None)
    assert len(network.requests_log) == 1


@pytest.mark.parametrize("endpoint", ["holidays", "countries", "languages"])
def test_missing_collection_fails_instead_of_erasing_table(endpoint: str) -> None:
    result = driver().run(endpoint, [ScriptedResponse(json={"meta": {"code": 200}, "response": {"unexpected": []}})])
    assert isinstance(result.raised, ValueError)
    assert "matched nothing" in str(result.raised)
    assert len(result.requests) == 1


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
