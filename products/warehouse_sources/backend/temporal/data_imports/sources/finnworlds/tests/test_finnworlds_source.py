from typing import Any

from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds.finnworlds import (
    MAX_COUNTRIES,
    MAX_TICKERS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds.source import FinnworldsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.finnworlds import (
    FinnworldsSourceConfig,
)


def _make_inputs(**overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = overrides.get("schema_name", "dividends")
    inputs.logger = overrides.get("logger", mock.MagicMock())
    return inputs


class TestFinnworldsSource:
    def setup_method(self) -> None:
        self.source = FinnworldsSource()
        self.team_id = 123
        self.config = FinnworldsSourceConfig(api_key="fw-test", tickers="AAPL, MSFT", countries="United Kingdom")

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["dividends"])
        assert [s.name for s in schemas] == ["dividends"]

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

    def test_validate_credentials_rejects_oversized_country_list(self) -> None:
        config = FinnworldsSourceConfig(
            api_key="fw-test", tickers="AAPL", countries=",".join(f"Country{i}" for i in range(MAX_COUNTRIES + 1))
        )
        with mock.patch.object(source_module, "validate_finnworlds_credentials") as probe:
            ok, message = self.source.validate_credentials(config, self.team_id)
        assert ok is False
        assert message is not None
        assert "Too many countries" in message
        probe.assert_not_called()

    def test_a_macro_only_source_needs_no_tickers(self) -> None:
        config = FinnworldsSourceConfig(api_key="fw-test", countries="Germany")
        inputs = _make_inputs(schema_name="macroeconomic_indicators")
        with mock.patch.object(source_module, "finnworlds_source") as mocked:
            self.source.source_for_pipeline(config, inputs)

        _, kwargs = mocked.call_args
        assert kwargs["tickers"] == []
        assert kwargs["countries"] == ["Germany"]

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
        assert kwargs["logger"] is inputs.logger
