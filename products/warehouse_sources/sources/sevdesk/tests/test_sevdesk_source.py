from collections.abc import Callable

import pytest
from unittest.mock import MagicMock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sevdesk import (
    SevdeskSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sevdesk.settings import REQUEST_TIMEOUT_SECONDS
from products.warehouse_sources.backend.temporal.data_imports.sources.sevdesk.source import SevdeskSource


@pytest.mark.parametrize("token", ["", "0" * 31, "0" * 33, "g" * 32, "0" * 31 + "\n", "é" * 32])
def test_rejects_malformed_tokens_before_http(token: str, http: MagicMock) -> None:
    valid, error = SevdeskSource().validate_credentials(SevdeskSourceConfig(api_token=token), team_id=1)
    assert not valid
    assert error is not None and "32-character hexadecimal" in error
    http.assert_not_called()


def test_rejects_unknown_schema(source_config: SevdeskSourceConfig, http: MagicMock) -> None:
    valid, error = SevdeskSource().validate_credentials(source_config, team_id=1, schema_name="../SevUser")
    assert not valid
    assert error is not None and "Unknown sevDesk table" in error
    http.assert_not_called()


@pytest.mark.parametrize(
    ("status", "schema_name", "expected_valid", "message"),
    [
        (200, None, True, None),
        (200, "InvoicePos", True, None),
        (401, None, False, "invalid or expired"),
        (401, "InvoicePos", False, "invalid or expired"),
        (403, None, True, None),
        (403, "InvoicePos", False, "permissions"),
    ],
)
def test_credential_probe_status_mapping(
    status: int,
    schema_name: str | None,
    expected_valid: bool,
    message: str | None,
    source_config: SevdeskSourceConfig,
    http: MagicMock,
    response: Callable[..., Response],
) -> None:
    http.return_value = response({"objects": []}, status)
    valid, error = SevdeskSource().validate_credentials(source_config, team_id=1, schema_name=schema_name)
    assert valid is expected_valid
    assert (error is None) if message is None else (error is not None and message in error)
    http.assert_called_once()
    request = http.call_args.args[0]
    assert request.url == f"https://my.sevdesk.de/api/v1/{schema_name or 'Contact'}?limit=1&offset=0"
    assert request.headers["Authorization"] == source_config.api_token
    assert http.call_args.kwargs["timeout"] == REQUEST_TIMEOUT_SECONDS


def test_does_not_disguise_request_errors_as_invalid_credentials(
    source_config: SevdeskSourceConfig, http: MagicMock, response: Callable[..., Response]
) -> None:
    http.return_value = response({"error": "bad_request"}, 400)
    with pytest.raises(HTTPError, match="400 Client Error"):
        SevdeskSource().validate_credentials(source_config, team_id=1)
    http.assert_called_once()
