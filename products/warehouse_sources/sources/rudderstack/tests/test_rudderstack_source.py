import pytest

from products.warehouse_sources.sources.rudderstack._config import RudderStackSourceConfig
from products.warehouse_sources.sources.rudderstack.source import RudderStackSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network


@pytest.mark.parametrize(
    ("schema_name", "status", "expected", "path", "token", "granularity"),
    [
        (None, 200, True, "/v2/workspace", "test-workspace-token", None),
        (None, 403, True, "/v2/workspace", "test-workspace-token", None),
        (None, 401, False, "/v2/workspace", "test-workspace-token", None),
        ("sources", 403, False, "/v2/sources", "test-workspace-token", None),
        ("audit_logs", 200, True, "/v2/audit-logs", "test-organization-token", None),
        ("retl_syncs", 200, True, "/v2/retl-connections", "test-workspace-token", None),
        ("tracking_plan_events", 200, True, "/v2/catalog/tracking-plans", "test-workspace-token", None),
        ("event_metrics_usage", 200, True, "/v2/organizations/usage/event-metrics", "test-organization-token", "day"),
        (None, 400, False, "/v2/workspace", "test-workspace-token", None),
    ],
)
def test_credential_probes_select_token_and_allow_missing_scope_only_at_creation(
    schema_name: str | None,
    status: int,
    expected: bool,
    path: str,
    token: str,
    granularity: str | None,
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
    assert request.param("granularity") == granularity


@pytest.mark.parametrize(
    ("token", "schema_name", "expected_message"),
    [
        ("", None, "Enter a valid"),
        ("token\nvalue", None, "Enter a valid"),
        ("tökén", None, "Enter a valid"),
        ("test-token", "unknown", "not supported"),
        ("test-token", "audit_logs", "organization Service Access Token"),
        ("test-token", "event_metrics_usage", "organization Service Access Token"),
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


@pytest.mark.parametrize(
    ("organization_access_token", "expected"),
    [
        (
            None,
            {
                "audit_logs": "Add an organization Service Access Token to sync the audit_logs table.",
                "event_metrics_usage": "Add an organization Service Access Token to sync the event_metrics_usage table.",
                "regulations": None,
            },
        ),
        ("test-organization-token", {"audit_logs": None, "event_metrics_usage": None, "regulations": None}),
    ],
)
def test_endpoint_permissions_flag_tables_that_need_the_organization_token(
    organization_access_token: str | None, expected: dict[str, str | None]
) -> None:
    config = RudderStackSourceConfig(access_token="test-token", organization_access_token=organization_access_token)

    assert RudderStackSource().get_endpoint_permissions(config, team_id=1, endpoints=list(expected)) == expected
