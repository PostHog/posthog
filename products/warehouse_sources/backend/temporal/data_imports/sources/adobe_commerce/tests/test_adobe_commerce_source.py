from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_commerce.settings import (
    ADOBE_COMMERCE_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_commerce.source import AdobeCommerceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adobecommerce import (
    AdobeCommerceAuthMethodConfig,
    AdobeCommerceSourceConfig,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.adobe_commerce.source"

INCREMENTAL_ENDPOINTS = (
    "orders",
    "invoices",
    "shipments",
    "creditmemos",
    "transactions",
    "products",
    "categories",
    "customers",
    "carts",
    "coupons",
)
FULL_REFRESH_ENDPOINTS = (
    "customer_groups",
    "product_attributes",
    "tax_classes",
    "store_views",
    "store_groups",
    "websites",
    "countries",
)


def _token_config(store_code: str | None = None) -> AdobeCommerceSourceConfig:
    return AdobeCommerceSourceConfig(
        store_url="https://store.example.com",
        store_code=store_code,
        auth_method=AdobeCommerceAuthMethodConfig(selection="access_token", access_token="tok-123"),
    )


class TestAdobeCommerceSource:
    def setup_method(self) -> None:
        self.source = AdobeCommerceSource()
        self.team_id = 123
        self.config = _token_config()

    def test_store_url_is_a_connection_host_field(self) -> None:
        # The token/password is sent to `store_url`, so retargeting it must force a re-entry.
        assert self.source.connection_host_fields == ["store_url"]

    def test_lists_tables_without_credentials(self) -> None:
        # `get_schemas` is a static catalog walk with no I/O, so public docs can render the tables.
        assert self.source.lists_tables_without_credentials is True

    def test_api_docs_url_is_https(self) -> None:
        assert self.source.api_docs_url is not None and self.source.api_docs_url.startswith("https://")

    @parameterized.expand([(endpoint,) for endpoint in INCREMENTAL_ENDPOINTS])
    def test_endpoints_with_a_server_side_timestamp_filter_are_incremental(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is True
        # Sales and catalog rows are rewritten in place, so append would duplicate them.
        assert schema.supports_append is False
        assert [f["field"] for f in schema.incremental_fields] == [
            ADOBE_COMMERCE_ENDPOINTS[endpoint].incremental_field_name
        ]

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
        for name, entry in descriptions.items():
            # Every documented table must at least describe its primary key columns.
            assert entry.get("columns"), name
            for key in ADOBE_COMMERCE_ENDPOINTS[name].primary_keys:
                assert key in entry["columns"], f"{name}.{key}"

    def test_incremental_fields_map_matches_the_endpoint_catalog(self) -> None:
        assert set(INCREMENTAL_FIELDS) == set(INCREMENTAL_ENDPOINTS)

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://store.example.com/rest/V1/orders"),
            ("forbidden", "403 Client Error: Forbidden for url: https://other.example.com/rest/V1/products"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://store.example.com/rest/V1/orders",
            ),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://store.example.com/rest/V1/orders"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        assert not any(key in unrelated_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("server_error", "Adobe Commerce admin token request failed (retryable): status=500"),
            ("rate_limited", "Adobe Commerce admin token request failed (retryable): status=429"),
        ]
    )
    def test_retryable_errors_match_admin_token_failures(self, _name: str, observed_error: str) -> None:
        # The admin token exchange only raises this once its own transport-level retries for
        # 429/5xx are exhausted, so it's self-recovering — it must stay out of error tracking.
        assert any(key in observed_error for key in self.source.get_retryable_errors())

    @mock.patch(f"{_MODULE}.adobe_commerce_source")
    def test_source_for_pipeline_plumbs_incremental_inputs(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "updated_at"
        inputs.db_incremental_field_last_value = "2024-05-04 03:02:01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["endpoint"] == "orders"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        # The user's chosen cursor from schema settings wins over the endpoint default.
        assert kwargs["incremental_field_name"] == "updated_at"
        assert kwargs["db_incremental_field_last_value"] == "2024-05-04 03:02:01"

    @mock.patch(f"{_MODULE}.adobe_commerce_source")
    def test_source_for_pipeline_drops_the_watermark_on_a_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "products"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-05-04 03:02:01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs: Any = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
