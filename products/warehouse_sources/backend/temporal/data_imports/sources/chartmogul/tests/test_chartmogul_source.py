from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.source import ChartMogulSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.chartmogul import (
    ChartMogulSourceConfig,
)


class TestChartMogulSource:
    def setup_method(self) -> None:
        self.source = ChartMogulSource()

    def test_validate_credentials_success(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.source.validate_chartmogul_credentials",
            return_value=True,
        ):
            valid, error = self.source.validate_credentials(ChartMogulSourceConfig(api_key="k"), team_id=1)
        assert valid is True
        assert error is None

    def test_validate_credentials_failure(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.source.validate_chartmogul_credentials",
            return_value=False,
        ):
            valid, error = self.source.validate_credentials(ChartMogulSourceConfig(api_key="bad"), team_id=1)
        assert valid is False
        assert error == "Invalid ChartMogul API key"
