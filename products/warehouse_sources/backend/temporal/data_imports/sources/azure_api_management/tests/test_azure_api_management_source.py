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


def _empty() -> ScriptedResponse:
    return ScriptedResponse(json={"tables": [{"name": "PrimaryResult", "columns": [], "rows": []}]})


def _basic_plan() -> ScriptedResponse:
    return ScriptedResponse(
        status=400,
        json={"error": {"code": "BadArgumentError", "message": "The query can't run on a table with the Basic plan."}},
    )


@pytest.mark.parametrize(
    ("gateway", "llm", "websocket", "expected_ok", "expected_probes"),
    [
        (
            _unresolved("ApiManagementGatewayLogs"),
            _unresolved("ApiManagementGatewayLlmLog"),
            _unresolved("ApiManagementWebSocketConnectionLogs"),
            False,
            3,
        ),
        (_basic_plan(), _empty(), _unresolved("ApiManagementWebSocketConnectionLogs"), True, 2),
    ],
)
def test_creation_fails_only_when_the_workspace_has_none_of_the_tables(
    gateway: ScriptedResponse,
    llm: ScriptedResponse,
    websocket: ScriptedResponse,
    expected_ok: bool,
    expected_probes: int,
) -> None:
    with scripted_network(
        route({TOKEN_PATH: [_token(), _token()], QUERY_PATH: [_empty(), gateway, llm, websocket]})
    ) as network:
        ok, message = AzureApiManagementSource().validate_credentials(CONFIG, team_id=1)

    assert ok is expected_ok
    if expected_ok:
        assert message is None
    else:
        assert message is not None and "This workspace has no API Management logs" in message
    queries = [request.json()["query"] for request in network.requests_log if request.path == QUERY_PATH]
    assert queries[0] == "print ok = 1"
    assert [query.split(" ")[0] for query in queries[1:]] == [
        "ApiManagementGatewayLogs",
        "ApiManagementGatewayLlmLog",
        "ApiManagementWebSocketConnectionLogs",
    ][:expected_probes]


def test_a_missing_named_table_points_at_its_log_category() -> None:
    with scripted_network(route({TOKEN_PATH: [_token()], QUERY_PATH: [_unresolved("ApiManagementGatewayLlmLog")]})):
        ok, message = AzureApiManagementSource().validate_credentials(
            CONFIG, team_id=1, schema_name="ApiManagementGatewayLlmLog"
        )

    assert ok is False
    assert message is not None and "no ApiManagementGatewayLlmLog logs yet. Turn on its log category" in message


def test_the_schema_picker_names_the_log_category_for_a_missing_table() -> None:
    with scripted_network(
        route(
            {
                TOKEN_PATH: [_token()],
                QUERY_PATH: [_empty(), _unresolved("ApiManagementGatewayLlmLog")],
            }
        )
    ):
        permissions = AzureApiManagementSource().get_endpoint_permissions(
            CONFIG, team_id=1, endpoints=["ApiManagementGatewayLogs", "ApiManagementGatewayLlmLog"]
        )

    assert permissions["ApiManagementGatewayLogs"] is None
    assert permissions["ApiManagementGatewayLlmLog"] is not None
    assert "log category" in permissions["ApiManagementGatewayLlmLog"]
