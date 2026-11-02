import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.optimizely import (
    OptimizelySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.source import OptimizelySource


class TestOptimizelySource:
    def setup_method(self) -> None:
        self.source = OptimizelySource()
        self.team_id = 123
        self.config = OptimizelySourceConfig(api_token="api-token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Optimizely personal access token"),
        ],
    )
    def test_validate_credentials(self, mock_return: bool, expected_valid: bool, expected_message: str | None) -> None:
        status = 200 if mock_return else 401
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert [request.path for request in network.requests_log] == ["/v2/projects"]
        assert network.requests_log[0].headers["authorization"] == "Bearer api-token"
