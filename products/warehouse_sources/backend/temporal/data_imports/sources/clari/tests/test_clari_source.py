import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.clari.source import ClariSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clari import ClariSourceConfig


class TestClariSource:
    def setup_method(self) -> None:
        self.source = ClariSource()
        self.team_id = 123
        self.config = ClariSourceConfig(api_key="key", forecast_id="fc-1")

    @pytest.mark.parametrize(
        "probe_succeeds, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    def test_validate_credentials(self, probe_succeeds: bool, expected_valid: bool) -> None:
        status_code = 200 if probe_succeeds else 401
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Clari credentials"
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["apikey"] == "key"
