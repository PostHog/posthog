import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.picqer import PicqerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.picqer import picqer_source
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.source import PicqerSource

# Endpoints whose Picqer list action exposes a genuine update-based `updated_after` filter.
_INCREMENTAL_ENDPOINTS = {"purchaseorders", "returns"}
_FULL_REFRESH_ENDPOINTS = set(ENDPOINTS) - _INCREMENTAL_ENDPOINTS


class TestPicqerSource:
    def setup_method(self):
        self.source = PicqerSource()
        self.team_id = 123
        self.config = PicqerSourceConfig(account_name="acme", api_key="key")

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

    def test_incremental_cursor_is_an_update_field(self):
        # The cursor must be an update timestamp so incremental catches modifications, not just new rows.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert [f["field"] for f in schemas["purchaseorders"].incremental_fields] == ["updated"]
        assert [f["field"] for f in schemas["returns"].incremental_fields] == ["updated_at"]

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


class TestPicqerSourceResponse:
    def test_partitioned_endpoint_uses_stable_created_field(self):
        # purchaseorders is incremental on `updated`, but must partition on the stable `created` field —
        # partitioning on `updated` would rewrite partitions on every sync.
        response = picqer_source(
            account="acme",
            api_key="key",
            endpoint="purchaseorders",
            team_id=1,
            job_id="job",
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
            team_id=1,
            job_id="job",
            resumable_source_manager=mock.MagicMock(),
        )
        assert response.primary_keys == ["idwarehouse"]
        assert response.partition_mode is None
        assert response.partition_keys is None
