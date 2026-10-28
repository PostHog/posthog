import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ortto import OrttoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.source import OrttoSource


class TestOrttoSource:
    def setup_method(self) -> None:
        self.source = OrttoSource()
        self.team_id = 123
        self.config = OrttoSourceConfig(api_key="key", region="eu")

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    def test_validate_credentials(self, mock_return: bool, expected_valid: bool) -> None:
        status = 200 if mock_return else 401
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Ortto credentials"
        assert network.requests_log[0].url == "https://api.eu.ap3api.com/v1/person/custom-field/get"
        assert network.requests_log[0].headers["x-api-key"] == "key"
