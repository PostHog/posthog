from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds.finnworlds import MAX_TICKERS
from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds.source import FinnworldsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.finnworlds import (
    FinnworldsSourceConfig,
)


class TestFinnworldsSource:
    def setup_method(self) -> None:
        self.source = FinnworldsSource()
        self.team_id = 123
        self.config = FinnworldsSourceConfig(api_key="fw-test", tickers="AAPL, MSFT")

    def test_validate_credentials_success(self) -> None:
        with mock.patch.object(source_module, "validate_finnworlds_credentials", return_value=(True, None)):
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        with mock.patch.object(
            source_module, "validate_finnworlds_credentials", return_value=(False, "Invalid Finnworlds API key")
        ):
            ok, message = self.source.validate_credentials(self.config, self.team_id)
        assert ok is False
        assert message is not None

    def test_validate_credentials_rejects_oversized_ticker_list(self) -> None:
        # Too many tickers is rejected at setup without ever probing the API, bounding outbound fan-out.
        config = FinnworldsSourceConfig(api_key="fw-test", tickers=",".join(f"T{i}" for i in range(MAX_TICKERS + 1)))
        with mock.patch.object(source_module, "validate_finnworlds_credentials") as probe:
            ok, message = self.source.validate_credentials(config, self.team_id)
        assert ok is False
        assert message is not None
        assert "Too many tickers" in message
        probe.assert_not_called()
