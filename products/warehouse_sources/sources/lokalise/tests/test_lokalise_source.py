import pytest

from products.warehouse_sources.sources.lokalise._config import LokaliseSourceConfig
from products.warehouse_sources.sources.lokalise.source import LokaliseSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network


@pytest.mark.parametrize(
    ("status", "schema_name", "valid", "message"),
    [
        (200, None, True, None),
        (401, None, False, "invalid or expired"),
        (400, None, False, "Try again"),
        (403, None, True, None),
        (403, "projects", False, "project permissions"),
        (200, "keys", True, None),
    ],
)
def test_credentials_distinguish_invalid_tokens_from_missing_permissions(
    status: int, schema_name: str | None, valid: bool, message: str | None
) -> None:
    with scripted_network(
        [ScriptedResponse(status=status, json={"projects": [], "error": {"code": status, "message": "Forbidden"}})]
    ) as network:
        result = LokaliseSource().validate_credentials(LokaliseSourceConfig(api_token="test-token"), 1, schema_name)
    assert result[0] is valid
    if message is None:
        assert result[1] is None
    else:
        assert message in (result[1] or "")
    assert network.requests_log[0].param("limit") == "1"


@pytest.mark.parametrize("status", [200, 401, 403])
def test_table_probe_checks_project_resource_permissions(status: int) -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"projects": [{"project_id": "project-a"}]}),
            ScriptedResponse(status=status, json={"keys": [], "error": {"code": status, "message": "Forbidden"}}),
        ]
    ) as network:
        result = LokaliseSource().validate_credentials(LokaliseSourceConfig(api_token="test-token"), 1, "keys")
    assert result[0] is (status == 200)
    assert [request.path for request in network.requests_log] == ["/api2/projects", "/api2/projects/project-a/keys"]


def test_unknown_table_fails_before_sending_credentials() -> None:
    with scripted_network([]) as network:
        valid, message = LokaliseSource().validate_credentials(
            LokaliseSourceConfig(api_token="test-token"), 1, "missing"
        )
    assert not valid
    assert message is not None and "not available" in message
    assert network.requests_log == []


@pytest.mark.parametrize(
    ("schema_name", "child_status", "valid"),
    [
        ("orders", 200, True),
        ("orders", 403, False),
        ("team_users", 403, True),
        ("team_users", 401, False),
    ],
)
def test_team_table_probe_checks_first_team(schema_name: str, child_status: int, valid: bool) -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"projects": []}),
            ScriptedResponse(json={"teams": [{"team_id": 7}]}),
            ScriptedResponse(status=child_status, json={"error": {"code": child_status, "message": "Denied"}}),
        ]
    ) as network:
        result = LokaliseSource().validate_credentials(LokaliseSourceConfig(api_token="test-token"), 1, schema_name)
    assert result[0] is valid
    child_path = "orders" if schema_name == "orders" else "users"
    assert [request.path for request in network.requests_log] == [
        "/api2/projects",
        "/api2/teams",
        f"/api2/teams/7/{child_path}",
    ]
