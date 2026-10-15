from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartlook import (
    SmartlookSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlook.source import SmartlookSource


@pytest.mark.parametrize(
    ("status", "body", "expected", "message"),
    [
        (200, {"projectId": "project-1"}, True, None),
        (401, {}, False, "rejected the API token"),
        (403, {}, False, "denied API access"),
        (400, {}, False, "could not validate"),
        (429, {}, False, "API request limit"),
        (503, {}, False, "unavailable"),
    ],
)
def test_credential_probe_maps_vendor_failures(
    status: int, body: dict[str, str], expected: bool, message: str | None
) -> None:
    config = SmartlookSourceConfig(api_token="test-token", region="us")
    with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
        valid, error = SmartlookSource().validate_credentials(config, team_id=1)
    assert valid is expected
    assert (error is None) if message is None else message in str(error)
    assert network.requests_log[0].url == "https://api.us.smartlook.cloud/api/v1/me"


def test_credential_probe_rejects_non_json_response() -> None:
    config = SmartlookSourceConfig(api_token="test-token", region="eu")
    with scripted_network([ScriptedResponse(body=b"<html>Unavailable</html>")]):
        valid, error = SmartlookSource().validate_credentials(config, team_id=1)
    assert not valid
    assert "invalid response" in str(error)


@pytest.mark.parametrize(
    ("token", "region", "message"),
    [
        ("", "eu", "API token"),
        ("token\n", "eu", "API token"),
        ("tökén", "eu", "API token"),
        ("test-token", "https://example.com", "EU or US"),
    ],
)
def test_invalid_connection_fields_do_not_send_credentials(token: str, region: Any, message: str) -> None:
    config = SmartlookSourceConfig(api_token=token, region=region)
    with scripted_network([]) as network:
        valid, error = SmartlookSource().validate_credentials(config, team_id=1)
    assert not valid
    assert message in str(error)
    assert not network.requests_log


@pytest.mark.parametrize(("table", "incremental"), [("unknown", False), ("visitors", True)])
def test_pipeline_rejects_unknown_tables_and_unsupported_sync_modes(table: str, incremental: bool) -> None:
    driver = SourceDriver(SmartlookSource(), SmartlookSourceConfig(api_token="test-token", region="eu"))
    result = driver.run(table, [], should_use_incremental_field=incremental)
    assert isinstance(result.raised, ValueError)
    assert not result.requests
