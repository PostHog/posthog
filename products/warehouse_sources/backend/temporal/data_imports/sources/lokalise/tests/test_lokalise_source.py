import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lokalise import (
    LokaliseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lokalise.source import LokaliseSource


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
