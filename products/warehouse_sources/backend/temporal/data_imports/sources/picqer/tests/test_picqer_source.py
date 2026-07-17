import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PicqerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.picqer import (
    PicqerResumeConfig,
    picqer_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.settings import ENDPOINTS, PICQER_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.source import PicqerSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Endpoints whose Picqer list action exposes a genuine update-based `updated_after` filter.
_INCREMENTAL_ENDPOINTS = {"purchaseorders", "returns"}
_FULL_REFRESH_ENDPOINTS = set(ENDPOINTS) - _INCREMENTAL_ENDPOINTS


class TestPicqerSource:
    def setup_method(self):
        self.source = PicqerSource()
        self.team_id = 123
        self.config = PicqerSourceConfig(account_name="acme", api_key="key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.PICQER

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Picqer"
        assert config.label == "Picqer"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/picqer.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/picqer"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["account_name", "api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_account_listed_as_connection_host_field(self):
        # The API key is sent to <account_name>.picqer.com, so retargeting it must re-require the key.
        assert self.source.connection_host_fields == ["account_name"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.picqer.com/api/v1/orders?offset=0",
            "403 Client Error: Forbidden for url: https://acme.picqer.com/api/v1/returns?offset=0",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://acme.picqer.com/api/v1/orders",
            "500 Server Error: Internal Server Error for url: https://acme.picqer.com/api/v1/orders",
            "HTTPSConnectionPool(host='acme.picqer.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert len(schemas[name].incremental_fields) == 1
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_incremental_cursor_is_an_update_field(self):
        # The cursor must be an update timestamp so incremental catches modifications, not just new rows.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert [f["field"] for f in schemas["purchaseorders"].incremental_fields] == ["updated"]
        assert [f["field"] for f in schemas["returns"].incremental_fields] == ["updated_at"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders"])
        assert len(schemas) == 1
        assert schemas[0].name == "orders"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(PICQER_ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            # 403 = valid key, insufficient scope — accepted at source-create (per-table scope reported separately).
            ((True, 403), True, None),
            ((False, 401), False, "Invalid Picqer API key"),
            ((False, None), False, "Could not connect to Picqer with the provided account name and API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.picqer.source.validate_picqer_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("acme", "key")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.picqer.source.validate_picqer_credentials"
    )
    def test_validate_credentials_surfaces_bad_account(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid Picqer account: 'a/b'.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Picqer account" in (error_message or "")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert manager._data_class is PicqerResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.picqer.source.picqer_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_picqer_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "purchaseorders"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2020-01-02 03:04:05"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_picqer_source.call_args.kwargs
        assert kwargs["account"] == "acme"
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "purchaseorders"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2020-01-02 03:04:05"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.picqer.source.picqer_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_picqer_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2020-01-02 03:04:05"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_picqer_source.call_args.kwargs["db_incremental_field_last_value"] is None


class TestPicqerSourceResponse:
    def test_partitioned_endpoint_uses_stable_created_field(self):
        # purchaseorders is incremental on `updated`, but must partition on the stable `created` field —
        # partitioning on `updated` would rewrite partitions on every sync.
        response = picqer_source(
            account="acme",
            api_key="key",
            endpoint="purchaseorders",
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
        )
        assert response.primary_keys == ["idpurchaseorder"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created"]

    def test_endpoint_without_created_field_is_unpartitioned(self):
        response = picqer_source(
            account="acme",
            api_key="key",
            endpoint="warehouses",
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
        )
        assert response.primary_keys == ["idwarehouse"]
        assert response.partition_mode is None
        assert response.partition_keys is None
