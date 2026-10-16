import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_api_management.source import (
    AzureApiManagementSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azureapimanagement import (
    AzureApiManagementSourceConfig,
)

TENANT = "11111111-1111-1111-1111-111111111111"
WORKSPACE = "22222222-2222-2222-2222-222222222222"
TOKEN_PATH = f"/{TENANT}/oauth2/v2.0/token"
QUERY_PATH = f"/v1/workspaces/{WORKSPACE}/query"
CONFIG = AzureApiManagementSourceConfig(
    tenant_id=TENANT, client_id="client", client_secret="secret", workspace_id=WORKSPACE
)
FUZZY_UNION = (
    "union isfuzzy=true ApiManagementGatewayLogs, ApiManagementGatewayLlmLog, "
    "ApiManagementWebSocketConnectionLogs | take 0"
)


def _token() -> ScriptedResponse:
    return ScriptedResponse(json={"token_type": "Bearer", "expires_in": 3599, "access_token": "token-1"})


def _unresolved(table: str) -> ScriptedResponse:
    return ScriptedResponse(
        status=400,
        json={
            "error": {
                "code": "BadArgumentError",
                "message": "The request had some invalid properties",
                "innererror": {
                    "code": "SemanticError",
                    "message": f"'union' operator: Failed to resolve table or column expression named '{table}'",
                },
            }
        },
    )


@pytest.mark.parametrize(
    ("schema_name", "expected_query", "expected_fragment"),
    [
        (None, FUZZY_UNION, "This workspace has no API Management logs"),
        (
            "ApiManagementGatewayLlmLog",
            "ApiManagementGatewayLlmLog | take 0",
            "no ApiManagementGatewayLlmLog logs yet. Turn on its log category",
        ),
    ],
)
def test_a_workspace_without_api_management_logs_points_at_the_diagnostic_setting(
    schema_name: str | None, expected_query: str, expected_fragment: str
) -> None:
    table = schema_name or "ApiManagementGatewayLogs"
    with scripted_network(route({TOKEN_PATH: [_token()], QUERY_PATH: [_unresolved(table)]})) as network:
        ok, message = AzureApiManagementSource().validate_credentials(CONFIG, team_id=1, schema_name=schema_name)

    assert ok is False
    assert message is not None and expected_fragment in message
    assert network.requests_log[-1].json()["query"] == expected_query


def test_the_schema_picker_names_the_log_category_for_a_missing_table() -> None:
    with scripted_network(
        route(
            {
                TOKEN_PATH: [_token()],
                QUERY_PATH: [
                    ScriptedResponse(json={"tables": [{"name": "PrimaryResult", "columns": [], "rows": []}]}),
                    _unresolved("ApiManagementGatewayLlmLog"),
                ],
            }
        )
    ):
        permissions = AzureApiManagementSource().get_endpoint_permissions(
            CONFIG, team_id=1, endpoints=["ApiManagementGatewayLogs", "ApiManagementGatewayLlmLog"]
        )

    assert permissions["ApiManagementGatewayLogs"] is None
    assert permissions["ApiManagementGatewayLlmLog"] is not None
    assert "log category" in permissions["ApiManagementGatewayLlmLog"]
