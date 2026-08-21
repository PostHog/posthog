import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.usbea import UsBeaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.us_bea.settings import CUSTOM_QUERY_ENDPOINT
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
