import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.loopreturns import (
    LoopReturnsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.source import LoopReturnsSource


class TestLoopReturnsSource:
    def setup_method(self) -> None:
        self.source = LoopReturnsSource()
        self.team_id = 1
        self.config = LoopReturnsSourceConfig(api_key="loop_test_key")

    @pytest.mark.parametrize("start_date", ["not-a-date", "2024-13-01", "1000-01-01"])
    def test_a_bad_start_date_is_rejected_before_calling_loop(self, start_date: str) -> None:
        config = LoopReturnsSourceConfig(api_key="loop_test_key", start_date=start_date)

        with scripted_network([]) as network:
            is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error is not None and "Start date" in error
        assert network.requests_log == []

    def test_a_valid_start_date_is_accepted(self) -> None:
        config = LoopReturnsSourceConfig(api_key="loop_test_key", start_date="2024-01-01")

        with scripted_network([ScriptedResponse(status=200)]):
            assert self.source.validate_credentials(config, self.team_id) == (True, None)

    def test_source_for_pipeline_builds_the_requested_table(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "advanced_shipping_notices", always(ScriptedResponse(json=[]))
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "advanced_shipping_notices"
        assert result.response.primary_keys == ["id", "return_line_item_id"]
