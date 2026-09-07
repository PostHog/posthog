import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.fred.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fred.settings import ENDPOINTS, FRED_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fred.source import FredSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fred import FredSourceConfig

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.fred.source"


class TestFredSource:
    def setup_method(self):
        self.source = FredSource()
        self.team_id = 123
        self.config = FredSourceConfig(api_key="key", series_ids="UNRATE, CPIAUCSL")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "FRED authentication failed: Bad Request.  The value for variable api_key is not registered.",
            "FRED rejected the request (path=/series): Bad Request.  The series does not exist.",
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "FRED API error: status=429, path=/series/observations, message=Too Many Requests.",
            "FRED API error: status=503, path=/releases, message=",
        ],
    )
    def test_non_retryable_errors_leave_transient_failures_retryable(self, other_error):
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # The pipeline hands a source one watermark for the whole table, but observations are
        # fetched per series and FRED restates published values, so nothing may claim
        # incremental sync off `observation_start`.
        assert not any(schema.supports_incremental for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

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

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_plumbs_schema_name(self, endpoint):
        inputs = mock.MagicMock()
        inputs.schema_name = endpoint

        response = self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert response.name == endpoint
        assert response.primary_keys == FRED_ENDPOINTS[endpoint].primary_keys

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.fred.source.fred_source")
    def test_source_for_pipeline_splits_the_series_id_field(self, mock_fred_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "observations"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_fred_source.call_args.kwargs["series_ids"] == ["UNRATE", "CPIAUCSL"]

    def test_canonical_descriptions_cover_every_endpoint(self):
        # Descriptions are keyed by schema name, so a renamed endpoint silently drops back to
        # LLM-derived descriptions.
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() == CANONICAL_DESCRIPTIONS
