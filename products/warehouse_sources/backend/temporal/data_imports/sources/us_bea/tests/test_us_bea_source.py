import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.usbea import UsBeaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.us_bea.settings import (
    CUSTOM_QUERY_ENDPOINT,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_bea.source import UsBeaSource


def _config(**overrides) -> UsBeaSourceConfig:
    return UsBeaSourceConfig(api_key="test-user-id", **overrides)


def _custom_config() -> UsBeaSourceConfig:
    return _config(custom_dataset_name="NIPA", custom_query_params="TableName=T10101,Frequency=Q,Year=ALL")


class _FakeInputs:
    def __init__(self, schema_name: str) -> None:
        self.schema_name = schema_name


class TestUsBeaSource:
    def setup_method(self):
        self.source = UsBeaSource()

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
        schemas = self.source.get_schemas(_config(), team_id=1, names=["StatePersonalIncomeSummary"])

        assert [schema.name for schema in schemas] == ["StatePersonalIncomeSummary"]

    @pytest.mark.parametrize(
        "overrides",
        [
            {"custom_dataset_name": "NIPA"},
            {"custom_dataset_name": "NIPA", "custom_query_params": ""},
            {"custom_query_params": "TableName=T10101"},
        ],
    )
    def test_validate_credentials_rejects_partial_custom_query(self, overrides):
        valid, error = self.source.validate_credentials(_config(**overrides), team_id=1)

        assert valid is False
        assert error is not None and "incomplete" in error

    def test_validate_credentials_delegates_to_transport(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.us_bea.source.validate_us_bea_credentials",
            return_value=(True, None),
        ) as mock_validate:
            valid, error = self.source.validate_credentials(_config(), team_id=1)

        assert (valid, error) == (True, None)
        mock_validate.assert_called_once_with("test-user-id")

    @pytest.mark.parametrize("endpoint_name", list(ENDPOINTS))
    def test_source_for_pipeline_builds_catalog_endpoint(self, endpoint_name):
        response = self.source.source_for_pipeline(_config(), _FakeInputs(endpoint_name))  # type: ignore[arg-type]

        assert response.name == endpoint_name
        assert response.primary_keys == list(ENDPOINTS[endpoint_name].primary_keys)

    def test_source_for_pipeline_custom_query_plumbing(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.us_bea.source.us_bea_source"
        ) as mock_source:
            self.source.source_for_pipeline(_custom_config(), _FakeInputs(CUSTOM_QUERY_ENDPOINT))  # type: ignore[arg-type]

        kwargs = mock_source.call_args.kwargs
        assert kwargs["custom_dataset_name"] == "NIPA"
        assert kwargs["custom_params"] == {"TableName": "T10101", "Frequency": "Q", "Year": "ALL"}
        assert kwargs["endpoint_config"] is None

    def test_source_for_pipeline_custom_query_unconfigured_raises(self):
        with pytest.raises(ValueError, match="BEA custom query"):
            self.source.source_for_pipeline(_config(), _FakeInputs(CUSTOM_QUERY_ENDPOINT))  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "error_message",
        [
            "BEA UserID is missing or invalid. Register a free UserID at https://apps.bea.gov/api/signup/",
            "BEA custom query is incomplete: set both the dataset name and the query parameters",
            "BEA API rejected the request: Invalid TableName",
        ],
    )
    def test_known_permanent_failures_are_non_retryable(self, error_message):
        non_retryable = self.source.get_non_retryable_errors()

        assert any(pattern in error_message for pattern in non_retryable)
