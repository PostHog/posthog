from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.sources.finnworlds import source as source_module
from products.warehouse_sources.sources.finnworlds._config import FinnworldsSourceConfig
from products.warehouse_sources.sources.finnworlds.finnworlds import MAX_COUNTRIES, MAX_CURRENCIES, MAX_TICKERS
from products.warehouse_sources.sources.finnworlds.source import FinnworldsSource


def _make_inputs(**overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = overrides.get("schema_name", "dividends")
    inputs.logger = overrides.get("logger", mock.MagicMock())
    return inputs


class TestFinnworldsSource:
    def setup_method(self) -> None:
        self.source = FinnworldsSource()
        self.team_id = 123
        self.config = FinnworldsSourceConfig(
            api_key="fw-test", tickers="AAPL, MSFT", countries="United Kingdom", currencies="usd eur"
        )

    def test_validate_credentials_failure(self) -> None:
        with mock.patch.object(
            source_module, "validate_finnworlds_credentials", return_value=(False, "Invalid Finnworlds API key")
        ):
            ok, message = self.source.validate_credentials(self.config, self.team_id)
        assert ok is False
        assert message is not None

    @parameterized.expand(
        [
            ("tickers", MAX_TICKERS, "Too many tickers"),
            ("countries", MAX_COUNTRIES, "Too many countries"),
            ("currencies", MAX_CURRENCIES, "Too many currencies"),
        ]
    )
    def test_validate_credentials_rejects_oversized_lists(self, field: str, limit: int, expected: str) -> None:
        # An oversized list is rejected at setup without ever probing the API, bounding outbound fan-out.
        config = FinnworldsSourceConfig(api_key="fw-test", **{field: ",".join(f"X{i}" for i in range(limit + 1))})
        with mock.patch.object(source_module, "validate_finnworlds_credentials") as probe:
            ok, message = self.source.validate_credentials(config, self.team_id)
        assert ok is False
        assert message is not None
        assert expected in message
        probe.assert_not_called()

    def test_a_macro_only_source_needs_no_tickers(self) -> None:
        config = FinnworldsSourceConfig(api_key="fw-test", countries="Germany")
        inputs = _make_inputs(schema_name="macroeconomic_indicators")
        with mock.patch.object(source_module, "finnworlds_source") as mocked:
            self.source.source_for_pipeline(config, inputs)

        _, kwargs = mocked.call_args
        assert kwargs["tickers"] == []
        assert kwargs["countries"] == ["Germany"]
        assert kwargs["currencies"] == []

    def test_source_for_pipeline_plumbs_parsed_tickers(self) -> None:
        inputs = _make_inputs(schema_name="dividends")
        with mock.patch.object(source_module, "finnworlds_source") as mocked:
            self.source.source_for_pipeline(self.config, inputs)

        mocked.assert_called_once()
        _, kwargs = mocked.call_args
        assert kwargs["api_key"] == "fw-test"
        assert kwargs["endpoint"] == "dividends"
        assert kwargs["tickers"] == ["AAPL", "MSFT"]
        assert kwargs["countries"] == ["United_Kingdom"]
        assert kwargs["currencies"] == ["USD", "EUR"]
        assert kwargs["logger"] is inputs.logger
