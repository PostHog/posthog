import pytest

import requests_mock
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.revolut_merchant.source import (
    RevolutMerchantSource,
)


@pytest.mark.parametrize("environment,host", [("production", "merchant"), ("sandbox", "sandbox-merchant")])
def test_full_refresh_and_probe_honor_environment_and_version(environment: str, host: str) -> None:
    source = RevolutMerchantSource()
    config = source.parse_config({"api_key": "test-secret-key", "environment": environment})
    result = SourceDriver(source, config).run(
        "customers",
        [ScriptedResponse(json={"customers": [{"id": "customer-1"}]})],
        api_version="2026-04-20",
    )
    assert result.items == [[{"id": "customer-1"}]]
    sync_request = result.requests[0]
    assert sync_request.origin == f"https://{host}.revolut.com"
    assert dict(sync_request.query) == {"limit": ("500",)}
    assert sync_request.headers["revolut-api-version"] == "2026-04-20"
    with scripted_network([ScriptedResponse(json={"customers": [{"id": "customer-1"}]})]) as network:
        assert source.validate_credentials(config, 1, api_version="2026-04-20") == (True, None)
    probe_request = network.requests_log[0]
    assert probe_request.origin == f"https://{host}.revolut.com"
    assert probe_request.headers["revolut-api-version"] == "2026-04-20"
    assert dict(probe_request.query) == {"limit": ("1",)}


@pytest.mark.parametrize("status,message", [(401, "Secret API key"), (403, "permissions"), (400, "API version")])
def test_sync_auth_and_version_failures_match_terminal_errors(status: int, message: str) -> None:
    source = RevolutMerchantSource()
    config = source.parse_config({"api_key": "test-secret-key", "environment": "production"})
    result = SourceDriver(source, config).run("customers", [ScriptedResponse(status=status, json={"code": "error"})])
    assert isinstance(result.raised, HTTPError)
    matches = [
        text
        for pattern, text in source.get_non_retryable_errors().items()
        if text is not None and pattern in str(result.raised)
    ]
    assert len(matches) == 1 and message in matches[0]
    assert len(result.requests) == 1
    assert result.saved_states == []


def test_environment_cannot_retarget_credentials(requests_mock: requests_mock.Mocker) -> None:
    source = RevolutMerchantSource()
    config = source.parse_config({"api_key": "test-secret-key", "environment": "https://example.com"})
    with pytest.raises(ValueError, match="Production or Sandbox"):
        source.validate_credentials(config, 1)
    assert requests_mock.call_count == 0
