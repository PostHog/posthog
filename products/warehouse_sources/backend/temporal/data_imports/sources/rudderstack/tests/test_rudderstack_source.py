import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rudderstack import (
    RudderStackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rudderstack.source import RudderStackSource


@pytest.mark.parametrize(
    ("schema_name", "status", "expected", "path", "token"),
    [
        (None, 200, True, "/v2/workspace", "test-workspace-token"),
        (None, 403, True, "/v2/workspace", "test-workspace-token"),
        (None, 401, False, "/v2/workspace", "test-workspace-token"),
        ("sources", 403, False, "/v2/sources", "test-workspace-token"),
        ("audit_logs", 200, True, "/v2/audit-logs", "test-organization-token"),
        ("retl_syncs", 200, True, "/v2/retl-connections", "test-workspace-token"),
        (None, 400, False, "/v2/workspace", "test-workspace-token"),
    ],
)
def test_credential_probes_select_token_and_allow_missing_scope_only_at_creation(
    schema_name: str | None,
    status: int,
    expected: bool,
    path: str,
    token: str,
) -> None:
    config = RudderStackSourceConfig(
        access_token="test-workspace-token",
        organization_access_token="test-organization-token",
        region="eu",
    )
    with scripted_network([ScriptedResponse(status=status, json={"message": "Unauthorized"})]) as network:
        valid, message = RudderStackSource().validate_credentials(config, team_id=1, schema_name=schema_name)

    assert valid is expected
    assert bool(message) is not expected
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.path == path
    assert request.origin == "https://api.eu.rudderstack.com"
    assert request.headers["authorization"] == f"Bearer {token}"


@pytest.mark.parametrize(
    ("token", "schema_name", "expected_message"),
    [
        ("", None, "Enter a valid"),
        ("token\nvalue", None, "Enter a valid"),
        ("tökén", None, "Enter a valid"),
        ("test-token", "unknown", "not supported"),
        ("test-token", "audit_logs", "organization Service Access Token"),
    ],
)
def test_invalid_configuration_fails_without_sending_a_request(
    token: str,
    schema_name: str | None,
    expected_message: str,
) -> None:
    with scripted_network([]) as network:
        valid, message = RudderStackSource().validate_credentials(
            RudderStackSourceConfig(access_token=token),
            team_id=1,
            schema_name=schema_name,
        )

    assert not valid
    assert message is not None and expected_message in message
    assert network.requests_log == []
