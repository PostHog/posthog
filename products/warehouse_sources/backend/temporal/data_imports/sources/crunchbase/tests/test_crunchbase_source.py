import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.source import CrunchbaseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.crunchbase import (
    CrunchbaseSourceConfig,
)


class TestCrunchbaseSource:
    def setup_method(self) -> None:
        self.source = CrunchbaseSource()
        self.team_id = 123
        self.config = CrunchbaseSourceConfig(api_key="user-key")

    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
        ],
    )
    def test_validate_credentials(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert "Enterprise/Applications" in (error_message or "")
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["x-cb-user-key"] == self.config.api_key
