from datetime import UTC, datetime, timedelta

import pytest

from requests import ConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.yotpo import YotpoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.yotpo.source import YotpoSource


@pytest.mark.parametrize(
    ("app_key", "secret", "start_date", "schema_name", "message"),
    [
        (" ", "test-secret", "2020-01-01", None, "Enter your Yotpo app key and API secret."),
        ("test-store", "", "2020-01-01", None, "Enter your Yotpo app key and API secret."),
        ("test-store", "test-secret", "2020-01-01", "unknown", "This Yotpo table is not supported."),
        (
            "test-store",
            "test-secret",
            "20200101",
            None,
            "Enter a start date in YYYY-MM-DD format that is not in the future.",
        ),
        (
            "test-store",
            "test-secret",
            "bad-date",
            None,
            "Enter a start date in YYYY-MM-DD format that is not in the future.",
        ),
        (
            "test-store",
            "test-secret",
            (datetime.now(UTC).date() + timedelta(days=1)).isoformat(),
            None,
            "Enter a start date in YYYY-MM-DD format that is not in the future.",
        ),
    ],
)
def test_invalid_configuration_fails_without_http(
    app_key: str, secret: str, start_date: str, schema_name: str | None, message: str
) -> None:
    with scripted_network([]) as network:
        result = YotpoSource().validate_credentials(
            YotpoSourceConfig(app_key=app_key, api_secret=secret, start_date=start_date), 1, schema_name=schema_name
        )
    assert result == (False, message)
    assert network.requests_log == []


@pytest.mark.parametrize(
    "status",
    [
        400,
    ],
)
def test_token_rejection_returns_a_credential_error(status: int) -> None:
    with scripted_network([ScriptedResponse(status=status, json={"error": "invalid_client"})]):
        result = YotpoSource().validate_credentials(
            YotpoSourceConfig(app_key="test-store", api_secret="test-secret", start_date="2020-01-01"), 1
        )
    assert result == (False, "Yotpo rejected the app key or API secret.")


@pytest.mark.parametrize("payload", [{}, {"access_token": None}, {"access_token": 1}])
def test_malformed_token_response_does_not_start_an_import(payload: dict[str, object]) -> None:
    with scripted_network([ScriptedResponse(json=payload)]) as network:
        result = YotpoSource().validate_credentials(
            YotpoSourceConfig(app_key="test-store", api_secret="test-secret", start_date="2020-01-01"), 1
        )
    assert result == (False, "Yotpo did not return an access token.")
    assert len(network.requests_log) == 1


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (ScriptedResponse(json={"reviews": []}), (True, None)),
        (
            ScriptedResponse(status=401, json={}),
            (False, "Yotpo rejected the access token. Check your app key and API secret."),
        ),
        (
            ScriptedResponse(status=403, json={}),
            (False, "Yotpo denied access to this table. Check your account's API access."),
        ),
        (ScriptedResponse(status=404, json={}), (False, "Yotpo could not validate your credentials. Try again.")),
        (
            ScriptedResponse(json={"error": "unsupported"}),
            (False, "Yotpo could not validate your credentials. Try again."),
        ),
    ],
)
def test_validation_reads_a_table_and_maps_permission_errors(
    response: ScriptedResponse, expected: tuple[bool, str | None]
) -> None:
    with scripted_network([ScriptedResponse(json={"access_token": "test-token"}), response]) as network:
        result = YotpoSource().validate_credentials(
            YotpoSourceConfig(app_key="test-store", api_secret="test-secret", start_date="2020-01-01"), 1
        )
    assert result == expected
    assert network.requests_log[1].param("count") == "1"


def test_connection_failure_returns_a_safe_error() -> None:
    with scripted_network(always(ConnectionError("test-secret"))):
        result = YotpoSource().validate_credentials(
            YotpoSourceConfig(app_key="test-store", api_secret="test-secret", start_date="2020-01-01"), 1
        )
    assert result == (False, "Yotpo could not validate your credentials. Try again.")
