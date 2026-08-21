from typing import Any

import pytest
from unittest import mock

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

    def test_api_docs_url_is_https(self) -> None:
        assert self.source.api_docs_url is not None and self.source.api_docs_url.startswith("https://")

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
