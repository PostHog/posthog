import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fred.settings import ENDPOINTS, FRED_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fred.source import FredSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fred import FredSourceConfig


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

        with scripted_network([]) as network:
            valid, error = self.source.validate_credentials(config, self.team_id)

        assert valid is False
        assert error == expected_error
        assert network.requests_log == []

    @pytest.mark.parametrize("is_valid", [True, False])
    def test_validate_credentials_probes_the_first_series(self, is_valid):
        response = (
            ScriptedResponse(json={"seriess": [{"id": "UNRATE"}]})
            if is_valid
            else ScriptedResponse(status=401, json={"error_message": "Bad key"})
        )

        with scripted_network([response]) as network:
            valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert valid is is_valid
        assert (error is None) is is_valid
        assert [request.param("series_id") for request in network.requests_log] == ["UNRATE"]
        assert [request.param("api_key") for request in network.requests_log] == ["key"]

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_plumbs_schema_name(self, endpoint):
        config = FRED_ENDPOINTS[endpoint]
        response = ScriptedResponse(json={config.data_key: []})
        result = SourceDriver(self.source, self.config).run(endpoint, [response] * (2 if config.per_series else 1))

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
