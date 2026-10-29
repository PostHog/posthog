import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.coda.source import CodaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coda import CodaSourceConfig


class TestCodaSource:
    def setup_method(self) -> None:
        self.source = CodaSource()
        self.team_id = 123
        self.config = CodaSourceConfig(api_token="api-token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Coda API token"),
        ],
    )
    def test_validate_credentials(self, mock_return: bool, expected_valid: bool, expected_message: str | None) -> None:
        with scripted_network([ScriptedResponse(status=200 if mock_return else 401)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/apis/v1/whoami"
        assert network.requests_log[0].headers["authorization"] == f"Bearer {self.config.api_token}"
