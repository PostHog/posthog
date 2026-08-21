import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.fred.settings import FRED_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fred.source import FredSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fred import FredSourceConfig

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.fred.source"


class TestFredSource:
    def setup_method(self):
        self.source = FredSource()
        self.team_id = 123
        self.config = FredSourceConfig(api_key="key", series_ids="UNRATE, CPIAUCSL")

    @pytest.mark.parametrize(
        "endpoint, config",
        list(FRED_ENDPOINTS.items()),
    )
    def test_series_scoped_tables_key_on_series_id(self, endpoint, config):
        # Rows from every configured series land in one table, so a key without `series_id`
        # is not unique table-wide and every later merge multi-matches it.
        if config.stamp_series_id:
            assert "series_id" in config.primary_keys
        else:
            assert "series_id" not in config.primary_keys

    @pytest.mark.parametrize(
        "series_ids, expected_error",
        [
            ("", "Enter at least one FRED series ID"),
            ("   ", "Enter at least one FRED series ID"),
            ("UNRATE, GDP*", "GDP* is not a valid FRED series ID. IDs look like UNRATE or CPIAUCSL."),
            (
                "https://fred.stlouisfed.org/series/UNRATE",
                "https://fred.stlouisfed.org/series/UNRATE is not a valid FRED series ID. IDs look like UNRATE or CPIAUCSL.",
            ),
        ],
    )
    def test_validate_credentials_rejects_bad_series_ids_without_calling_fred(self, series_ids, expected_error):
        config = FredSourceConfig(api_key="key", series_ids=series_ids)

        with mock.patch(f"{SOURCE_MODULE}.validate_fred_credentials") as mock_validate:
            valid, error = self.source.validate_credentials(config, self.team_id)

        assert valid is False
        assert error == expected_error
        mock_validate.assert_not_called()

    @pytest.mark.parametrize("is_valid", [True, False])
    @mock.patch(f"{SOURCE_MODULE}.validate_fred_credentials")
    def test_validate_credentials_probes_the_first_series(self, mock_validate, is_valid):
        mock_validate.return_value = (is_valid, None if is_valid else "Invalid FRED API key.")

        valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert valid is is_valid
        assert (error is None) is is_valid
        mock_validate.assert_called_once_with("key", "UNRATE")
