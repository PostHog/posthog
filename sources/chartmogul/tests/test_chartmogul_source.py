from unittest.mock import patch

from sources.chartmogul._config import ChartMogulSourceConfig
from sources.chartmogul.source import ChartMogulSource


class TestChartMogulSource:
    def setup_method(self) -> None:
        self.source = ChartMogulSource()

    def test_validate_credentials_success(self) -> None:
        with patch(
            "sources.chartmogul.source.validate_chartmogul_credentials",
            return_value=True,
        ):
            valid, error = self.source.validate_credentials(ChartMogulSourceConfig(api_key="k"), team_id=1)
        assert valid is True
        assert error is None

    def test_validate_credentials_failure(self) -> None:
        with patch(
            "sources.chartmogul.source.validate_chartmogul_credentials",
            return_value=False,
        ):
            valid, error = self.source.validate_credentials(ChartMogulSourceConfig(api_key="bad"), team_id=1)
        assert valid is False
        assert error == "Invalid ChartMogul API key"
