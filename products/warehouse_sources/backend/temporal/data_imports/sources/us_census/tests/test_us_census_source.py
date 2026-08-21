import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.uscensus import (
    USCensusSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_census.settings import CUSTOM_QUERY_ENDPOINT
from products.warehouse_sources.backend.temporal.data_imports.sources.us_census.source import USCensusSource


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
