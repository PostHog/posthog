import json
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.retellai import (
    RetellAISourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.retell_ai.source import RetellAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.retell_ai.tests.conftest import response


@pytest.mark.parametrize("status", [200, 401, 403])
@pytest.mark.parametrize("name", [None, "agents", "chats", "phone_numbers", "voices"])
def test_scoped_credential_probes(status: int, name: str | None, http: MagicMock) -> None:
    http.return_value = response(
        [] if name == "voices" else {"items": [], "has_more": True, "pagination_key": "unused"}, status
    )
    success, error = RetellAISource().validate_credentials(
        RetellAISourceConfig(api_key="fake-key"), 1, schema_name=name
    )
    assert success is (status == 200 or (status == 403 and name is None))
    if success:
        assert error is None
    elif status == 401:
        assert error is not None and "invalid or expired" in error
    else:
        assert error is not None and "permissions" in error
    assert http.call_count == 1
    request = http.call_args.args[1]
    if name in (None, "chats"):
        assert json.loads(request.body)["limit"] == 1
    elif name != "voices":
        assert parse_qs(urlsplit(request.url).query)["limit"] == ["1"]


@pytest.mark.parametrize("key", ["", "fake key", "fake-key\n", "clé-example", "fake\rkey"])
def test_malformed_api_keys_fail_before_http(key: str, http: MagicMock) -> None:
    success, error = RetellAISource().validate_credentials(RetellAISourceConfig(api_key=key), 1)
    assert success is False
    assert error is not None and "valid Retell AI API key" in error
    http.assert_not_called()


@pytest.mark.parametrize(
    "status,expected",
    [
        (400, HTTPError),
        (429, (False, "Couldn't reach Retell AI to check your credentials. Try again in a few minutes.")),
        (500, (False, "Couldn't reach Retell AI to check your credentials. Try again in a few minutes.")),
    ],
)
def test_probe_errors_are_not_reported_as_invalid_credentials(
    status: int,
    expected: type[Exception] | tuple[bool, str],
    http: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    http.return_value = response({}, status)
    source = RetellAISource()
    config = RetellAISourceConfig(api_key="fake-key")
    if isinstance(expected, tuple):
        assert source.validate_credentials(config, 1) == expected
    else:
        with pytest.raises(expected):
            source.validate_credentials(config, 1)
