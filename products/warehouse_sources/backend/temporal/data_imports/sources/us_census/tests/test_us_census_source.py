import pytest
from unittest.mock import patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.uscensus import (
    USCensusSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_census.settings import (
    CUSTOM_QUERY_ENDPOINT,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_census.source import USCensusSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(**overrides) -> USCensusSourceConfig:
    return USCensusSourceConfig(api_key="test-key", **overrides)


def _custom_config() -> USCensusSourceConfig:
    return _config(
        custom_dataset="2024/acs/acs5",
        custom_variables="NAME,B01001_001E",
        custom_geography="state:*",
    )


class _FakeInputs:
    def __init__(self, schema_name: str) -> None:
        self.schema_name = schema_name


class TestUSCensusSource:
    def setup_method(self):
        self.source = USCensusSource()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.USCENSUS

    def test_source_config_is_released_alpha(self):
        config = self.source.get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/us-census"

    def test_source_config_fields(self):
        fields = {field.name: field for field in self.source.get_source_config.fields}

        api_key_field = fields["api_key"]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.required is True
        assert api_key_field.secret is True
        for name in ("custom_dataset", "custom_variables", "custom_geography", "custom_geography_filter"):
            custom_field = fields[name]
            assert isinstance(custom_field, SourceFieldInputConfig)
            assert custom_field.required is False

    def test_get_schemas_static_catalog(self):
        schemas = self.source.get_schemas(_config(), team_id=1)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        assert all(schema.supports_incremental is False for schema in schemas)
        assert all(schema.supports_append is False for schema in schemas)
        assert all(schema.description for schema in schemas)

    def test_get_schemas_includes_custom_query_when_configured(self):
        schemas = self.source.get_schemas(_custom_config(), team_id=1)

        assert [schema.name for schema in schemas] == [*ENDPOINTS, CUSTOM_QUERY_ENDPOINT]

    def test_get_schemas_names_filter(self):
        schemas = self.source.get_schemas(_config(), team_id=1, names=["AcsDemographicsByState"])

        assert [schema.name for schema in schemas] == ["AcsDemographicsByState"]

    @pytest.mark.parametrize(
        "overrides",
        [
            {"custom_dataset": "2024/acs/acs5"},
            {"custom_dataset": "2024/acs/acs5", "custom_variables": "NAME"},
            {"custom_variables": "NAME", "custom_geography": "state:*"},
        ],
    )
    def test_validate_credentials_rejects_partial_custom_query(self, overrides):
        valid, error = self.source.validate_credentials(_config(**overrides), team_id=1)

        assert valid is False
        assert error is not None and "incomplete" in error

    def test_validate_credentials_delegates_to_transport(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.us_census.source.validate_us_census_credentials",
            return_value=(True, None),
        ) as mock_validate:
            valid, error = self.source.validate_credentials(_config(), team_id=1)

        assert (valid, error) == (True, None)
        mock_validate.assert_called_once_with("test-key")

    @pytest.mark.parametrize("endpoint_name", list(ENDPOINTS))
    def test_source_for_pipeline_builds_catalog_endpoint(self, endpoint_name):
        response = self.source.source_for_pipeline(_config(), _FakeInputs(endpoint_name))  # type: ignore[arg-type]

        assert response.name == endpoint_name
        assert response.primary_keys == list(ENDPOINTS[endpoint_name].primary_keys)

    def test_source_for_pipeline_custom_query_plumbing(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.us_census.source.us_census_source"
        ) as mock_source:
            self.source.source_for_pipeline(_custom_config(), _FakeInputs(CUSTOM_QUERY_ENDPOINT))  # type: ignore[arg-type]

        kwargs = mock_source.call_args.kwargs
        assert kwargs["dataset"] == "2024/acs/acs5"
        assert kwargs["variables"] == ("NAME", "B01001_001E")
        assert kwargs["geography"] == "state:*"
        assert kwargs["geography_filter"] is None
        assert kwargs["primary_keys"] is None

    def test_source_for_pipeline_custom_query_unconfigured_raises(self):
        with pytest.raises(ValueError, match="US Census custom query"):
            self.source.source_for_pipeline(_config(), _FakeInputs(CUSTOM_QUERY_ENDPOINT))  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "error_message",
        [
            "US Census API key is missing or invalid. Request a free key at https://api.census.gov/data/key_signup.html",
            "US Census API rejected the request (400): error: unknown variable 'B99999_999E'",
            "US Census API rejected the request (400): error: unsupported geography hierarchy",
            "US Census custom query is incomplete: set the dataset path, variables, and geography together",
            "US Census API response is too large (over 256 MiB). Narrow the query with fewer variables or a smaller geography (e.g. an in= filter).",
        ],
    )
    def test_known_permanent_failures_are_non_retryable(self, error_message):
        non_retryable = self.source.get_non_retryable_errors()

        assert any(pattern in error_message for pattern in non_retryable)

    def test_canonical_descriptions_cover_catalog_endpoints(self):
        descriptions = self.source.get_canonical_descriptions()

        for endpoint_name in ENDPOINTS:
            assert endpoint_name in descriptions
            assert descriptions[endpoint_name].get("description")
