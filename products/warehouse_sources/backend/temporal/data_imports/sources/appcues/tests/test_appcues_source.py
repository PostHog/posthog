from dataclasses import replace
from typing import Any

import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.appcues.source import AppcuesSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appcues import (
    AppcuesSourceConfig,
)


@pytest.mark.parametrize(
    ("status", "schema_name", "valid", "message"),
    [
        (200, None, True, None),
        (200, "flows_v2", True, None),
        (401, None, False, "rejected your API key or secret"),
        (403, None, True, None),
        (403, "segments", False, "cannot read this table"),
        (404, None, False, "Check your account ID and region"),
    ],
)
def test_credential_probe_maps_authentication_and_table_permission_failures(
    status: int, schema_name: str | None, valid: bool, message: str | None
) -> None:
    config = AppcuesSourceConfig(api_key="test-key", api_secret="test-secret", account_id="12345", region="eu")
    body = [] if status == 200 else {"error": True, "status": status, "title": "Access denied"}
    with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
        result = AppcuesSource().validate_credentials(config, team_id=1, schema_name=schema_name)

    assert result[0] is valid
    if message is None:
        assert result[1] is None
    else:
        assert result[1] is not None and message in result[1]
    path = "flows-v2" if schema_name == "flows_v2" else schema_name or "flows"
    assert network.requests_log[0].url == f"https://api.eu.appcues.com/v2/accounts/12345/{path}"


def test_credential_probe_does_not_hide_unexpected_http_errors() -> None:
    config = AppcuesSourceConfig(api_key="test-key", api_secret="test-secret", account_id="12345", region="us")
    with scripted_network([ScriptedResponse(status=400, json={"error": True, "status": 400})]):
        with pytest.raises(HTTPError):
            AppcuesSource().validate_credentials(config, team_id=1)


@pytest.mark.parametrize(
    ("changes", "schema_name", "api_version", "message"),
    [
        ({"region": "https://example.com"}, None, None, "Select the US or EU region"),
        ({"account_id": "../another-account"}, None, None, "Enter the Appcues account ID"),
        ({"account_id": "12345?limit=1"}, None, None, "Enter the Appcues account ID"),
        ({"api_key": ""}, None, None, "Enter a valid Appcues API key and secret"),
        ({"api_secret": "\u200btest-secret"}, None, None, "Enter a valid Appcues API key and secret"),
        ({"api_key": "key:secret"}, None, None, "in separate fields"),
        ({}, "unknown-table", None, "Select a listed table"),
        ({}, None, "v1", "Reconnect the source with version v2"),
    ],
)
def test_invalid_connection_input_fails_before_sending_credentials(
    changes: dict[str, Any], schema_name: str | None, api_version: str | None, message: str
) -> None:
    config = replace(
        AppcuesSourceConfig(api_key="test-key", api_secret="test-secret", account_id="12345", region="us"), **changes
    )
    with scripted_network([]) as network:
        valid, error = AppcuesSource().validate_credentials(config, 1, schema_name, api_version)

    assert not valid
    assert error is not None and message in error
    assert network.requests_log == []
