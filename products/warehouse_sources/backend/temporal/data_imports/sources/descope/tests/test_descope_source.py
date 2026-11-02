import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.descope.source import DescopeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.descope import (
    DescopeSourceConfig,
)


class TestDescopeSource:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
        ],
    )
    def test_validate_credentials(self, status_code: int, expected_valid: bool) -> None:
        config = DescopeSourceConfig(project_id="P2abc", management_key="mgmt-key")
        with scripted_network([ScriptedResponse(status=status_code, json={})]) as network:
            is_valid, error_message = DescopeSource().validate_credentials(config, team_id=123)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message
        assert network.requests_log[0].path == "/v1/mgmt/projects/list"
        assert network.requests_log[0].headers["authorization"] == "Bearer P2abc:mgmt-key"
