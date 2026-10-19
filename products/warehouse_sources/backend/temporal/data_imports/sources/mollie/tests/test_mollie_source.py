import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mollie import MollieSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mollie.source import MollieSource


class TestMollieSource:
    def setup_method(self) -> None:
        self.source = MollieSource()
        self.team_id = 123
        self.config = MollieSourceConfig(api_key="live_key")

    @pytest.mark.parametrize(
        "valid_response, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Mollie API key"),
        ],
    )
    def test_validate_credentials(
        self, valid_response: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        status = 200 if valid_response else 401
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["authorization"] == f"Bearer {self.config.api_key}"
