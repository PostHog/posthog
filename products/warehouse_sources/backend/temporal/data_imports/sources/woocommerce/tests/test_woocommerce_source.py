from typing import Optional

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WooCommerceSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PARTITION_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source import WooCommerceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce import (
    WooCommerceResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = set(INCREMENTAL_FIELDS.keys())


def _make_inputs(schema_name: str, should_use_incremental_field: bool = False, last_value: object = None):
    return mock.MagicMock(
        schema_name=schema_name,
        team_id=123,
        job_id="job-1",
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=last_value,
    )


class TestWooCommerceSource:
    def setup_method(self):
        self.source = WooCommerceSource()
        self.team_id = 123
        self.config = WooCommerceSourceConfig(
            store_url="https://example.com",
            consumer_key="ck_test",
            consumer_secret="cs_test",
        )

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.WOOCOMMERCE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "WooCommerce"
        assert config.label == "WooCommerce"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/woocommerce.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["store_url", "consumer_key", "consumer_secret"]

        consumer_secret = config.fields[2]
        assert isinstance(consumer_secret, SourceFieldInputConfig)
        assert consumer_secret.type == SourceFieldInputConfigType.PASSWORD
        assert consumer_secret.secret is True
        assert consumer_secret.required is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_get_schemas_incremental_only_for_supported_endpoints(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        expected = endpoint in INCREMENTAL_ENDPOINTS

        assert schema.supports_incremental is expected
        assert schema.supports_append is expected
        if expected:
            assert schema.incremental_fields[0]["field"] == "date_modified_gmt"
        else:
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders"])
        assert [s.name for s in schemas] == ["orders"]

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid",
        [
            (200, None, True),
            (200, "orders", True),
            (401, None, False),
            (403, None, True),  # valid key without scope for the probe endpoint -> allowed at create
            (403, "orders", False),  # but rejected for a specific schema check
            (404, None, False),
            (None, None, False),  # connection error
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source.validate_woocommerce_credentials"
    )
    def test_validate_credentials(self, mock_validate, status, schema_name, expected_valid):
        mock_validate.return_value = status

        is_valid, _ = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        mock_validate.assert_called_once_with("https://example.com", "ck_test", "cs_test", self.team_id)

    def test_validate_credentials_missing_fields(self):
        config = WooCommerceSourceConfig(store_url="", consumer_key="", consumer_secret="")
        is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message == "Missing WooCommerce credentials"

    def test_get_resumable_source_manager(self):
        manager = self.source.get_resumable_source_manager(_make_inputs("orders"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is WooCommerceResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source.woocommerce_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source):
        mock_resource = mock.MagicMock(name="orders", column_hints=None)
        mock_source.return_value = mock_resource
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = _make_inputs("orders", should_use_incremental_field=True, last_value="2024-01-01T00:00:00")

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["store_url"] == "https://example.com"
        assert kwargs["consumer_key"] == "ck_test"
        assert kwargs["consumer_secret"] == "cs_test"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "desc"

    def test_source_for_pipeline_full_refresh_drops_last_value(self):
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = _make_inputs("customers", should_use_incremental_field=False, last_value="2024-01-01T00:00:00")

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source.woocommerce_source"
        ) as mock_source:
            mock_source.return_value = mock.MagicMock(name="customers", column_hints=None)
            response = self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
        assert response.sort_mode == "asc"

    def test_source_for_pipeline_ignores_incremental_for_non_incremental_endpoint(self):
        # A non-incremental endpoint must stay full refresh even if the flag is set, so it
        # doesn't advertise desc semantics or carry a cursor value it can't honor.
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = _make_inputs("customers", should_use_incremental_field=True, last_value="2024-01-01T00:00:00")

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source.woocommerce_source"
        ) as mock_source:
            mock_source.return_value = mock.MagicMock(name="customers", column_hints=None)
            response = self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_source_for_pipeline_partitioning(self, endpoint):
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = _make_inputs(endpoint)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source.woocommerce_source"
        ) as mock_source:
            mock_source.return_value = mock.MagicMock(name=endpoint, column_hints=None)
            response = self.source.source_for_pipeline(self.config, manager, inputs)

        expected_key: Optional[str] = PARTITION_FIELDS.get(endpoint)
        if expected_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [expected_key]
        else:
            assert response.partition_keys is None
