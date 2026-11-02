import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vwo import VWOSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vwo.source import VWOSource


@pytest.mark.parametrize(
    "account_id,token,schema_name,message",
    [
        ("0", "test-token", None, "positive numeric"),
        ("../other", "test-token", None, "positive numeric"),
        ("１２３", "test-token", None, "positive numeric"),
        ("123", "", None, "API token without spaces"),
        ("123", "test\ntoken", None, "API token without spaces"),
        ("123", "tökén", None, "API token without spaces"),
        ("123", "test-token", "unknown", "not supported"),
    ],
)
def test_invalid_inputs_do_not_send_credentials(
    account_id: str, token: str, schema_name: str | None, message: str
) -> None:
    with scripted_network([]) as network:
        valid, error = VWOSource().validate_credentials(
            VWOSourceConfig(account_id=account_id, api_token=token), 1, schema_name=schema_name
        )
    assert not valid
    assert error is not None and message in error
    assert network.requests_log == []


@pytest.mark.parametrize(
    "status,body,valid,message",
    [
        (200, {"_data": {"id": 123}}, True, None),
        (200, {"_errors": [{"message": "Authentication Failed"}]}, False, "returned no workspace"),
        (401, {"_errors": [{"message": "Authentication Failed"}]}, False, "rejected the API token"),
        (403, {"_errors": [{"message": "Permission denied"}]}, False, "cannot read this workspace"),
        (404, {"_errors": [{"message": "Not found"}]}, False, "could not find this workspace"),
        (400, {"_errors": [{"message": "Bad Request"}]}, False, "rejected the connection request"),
        (503, {}, False, "Could not connect"),
    ],
)
def test_credential_probe_maps_errors_without_requiring_table_scopes(
    status: int, body: dict[str, object], valid: bool, message: str | None
) -> None:
    with scripted_network([ScriptedResponse(status=status, json=body)] * 5) as network:
        result, error = VWOSource().validate_credentials(VWOSourceConfig(account_id="123", api_token="test-token"), 1)
    assert result is valid
    assert error is None if message is None else error is not None and message in error
    assert network.requests_log[0].path == "/api/v2/accounts/123"
    assert network.requests_log[0].headers["token"] == "test-token"
