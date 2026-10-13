import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.umami import UmamiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.umami.source import UmamiSource


@pytest.mark.parametrize(
    "status, schema_name, valid, error_fragment",
    [
        (200, None, True, None),
        (401, None, False, "rejected"),
        (403, None, True, None),
        (403, "events", False, "denied"),
        (200, "events", False, "website list"),
    ],
)
def test_validation_maps_vendor_denials_without_blocking_partial_access(
    status: int, schema_name: str | None, valid: bool, error_fragment: str | None
) -> None:
    body: dict[str, object] = (
        {"data": []} if schema_name is None and status == 200 else {"error": {"code": "unauthorized"}}
    )
    with scripted_network([ScriptedResponse(status=status, json=body)]):
        result, error = UmamiSource().validate_credentials(UmamiSourceConfig(api_key="fake-key"), 1, schema_name)
    assert result == valid
    if error_fragment:
        assert error_fragment in (error or "")
    else:
        assert error is None


@pytest.mark.parametrize(
    "config, error_fragment",
    [
        ({}, "Enter an API key"),
        ({"username": "reader", "password": "fake-password"}, "Enter an API key"),
        ({"host": "https://api.umami.is/api", "api_key": "fake-key"}, "Umami Cloud"),
        ({"host": "https://fake-key@analytics.example.com/api", "api_key": "fake-key"}, "HTTPS API URL"),
    ],
)
def test_bad_connection_settings_do_not_send_credentials(config: dict[str, str], error_fragment: str) -> None:
    with scripted_network([]) as network:
        valid, error = UmamiSource().validate_credentials(UmamiSourceConfig(**config), 1)
    assert not valid
    assert error_fragment in (error or "")
    assert network.requests == 0


@pytest.mark.parametrize(
    "body, error_fragment",
    [
        ({"requiresTwoFactor": True, "partialToken": "fake-partial-token"}, "two-factor"),
        ({"user": {"username": "reader"}}, "login token"),
    ],
)
def test_login_without_a_usable_token_stops_before_reading_websites(
    body: dict[str, object], error_fragment: str
) -> None:
    config = UmamiSourceConfig(host="https://analytics.example.com/api", username="reader", password="fake-password")
    with scripted_network([ScriptedResponse(json=body)]) as network:
        valid, error = UmamiSource().validate_credentials(config, 1)
    assert not valid
    assert error_fragment in (error or "")
    assert len(network.requests_log) == 1


@pytest.mark.parametrize(
    "table, incremental, error_fragment",
    [
        ("missing", False, "Unknown Umami table"),
        ("events", True, "full refresh"),
    ],
)
def test_invalid_pipeline_request_stops_before_http(table: str, incremental: bool, error_fragment: str) -> None:
    result = SourceDriver(UmamiSource(), UmamiSourceConfig(api_key="fake-key")).run(
        table, [], should_use_incremental_field=incremental
    )
    assert error_fragment in str(result.raised)
    assert result.requests == []


@pytest.mark.parametrize("status", [401, 403])
def test_denied_login_cannot_create_a_source(status: int) -> None:
    config = UmamiSourceConfig(host="https://analytics.example.com/api", username="reader", password="fake-password")
    with scripted_network([ScriptedResponse(status=status, json={"error": {"code": "unauthorized"}})]) as network:
        valid, error = UmamiSource().validate_credentials(config, 1)
    assert not valid
    assert error is not None
    assert len(network.requests_log) == 1
