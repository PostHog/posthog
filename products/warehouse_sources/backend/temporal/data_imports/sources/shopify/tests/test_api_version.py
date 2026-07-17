from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ShopifySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.constants import (
    ORDERS,
    SHOPIFY_API_VERSION_2025_10,
    SHOPIFY_API_VERSION_2026_07,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import shopify_source
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source import ShopifySource


def _make_inputs(api_version: str | None) -> MagicMock:
    inputs = MagicMock()
    inputs.schema_name = ORDERS
    inputs.api_version = api_version
    inputs.should_use_incremental_field = False
    inputs.db_incremental_field_last_value = None
    inputs.db_incremental_field_earliest_value = None
    return inputs


class TestApiVersionResolution:
    def test_default_version_is_current(self) -> None:
        assert ShopifySource.default_version == SHOPIFY_API_VERSION_2026_07
        assert set(ShopifySource.supported_versions) == {SHOPIFY_API_VERSION_2025_10, SHOPIFY_API_VERSION_2026_07}

    @pytest.mark.parametrize(
        "pin, expected",
        [
            (SHOPIFY_API_VERSION_2025_10, SHOPIFY_API_VERSION_2025_10),
            (SHOPIFY_API_VERSION_2026_07, SHOPIFY_API_VERSION_2026_07),
            # An unpinned source resolves to the current default rather than the legacy version.
            (None, SHOPIFY_API_VERSION_2026_07),
        ],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source.shopify_source")
    def test_resolved_pin_reaches_request_layer(
        self, mock_shopify_source: MagicMock, pin: str | None, expected: str
    ) -> None:
        source = ShopifySource()
        config = ShopifySourceConfig(
            shopify_store_id="my-store", shopify_client_id="client-id", shopify_client_secret="secret"
        )

        source.source_for_pipeline(config, MagicMock(spec=ResumableSourceManager), _make_inputs(pin))

        assert mock_shopify_source.call_args.kwargs["api_version"] == expected


class TestApiVersionReachesRequestUrl:
    @pytest.mark.parametrize("api_version", [SHOPIFY_API_VERSION_2025_10, SHOPIFY_API_VERSION_2026_07])
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify._get_shopify_access_token",
        return_value="test-token",
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify.requests.Session")
    def test_version_is_the_url_segment(self, session_cls: MagicMock, _mock_token: MagicMock, api_version: str) -> None:
        posted_urls: list[str] = []

        def _post(url: str, json: dict[str, Any] | None = None, **kwargs: Any) -> MagicMock:
            posted_urls.append(url)
            response = MagicMock()
            response.status_code = 200
            response.ok = True
            response.json.return_value = {
                "data": {ORDERS: {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
            }
            return response

        session_cls.return_value.post.side_effect = _post

        source = shopify_source(
            shopify_store_id="my-store",
            shopify_client_id="id",
            shopify_client_secret="secret",
            graphql_object_name=ORDERS,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
            api_version=api_version,
        )
        list(source.items())

        assert posted_urls == [f"https://my-store.myshopify.com/admin/api/{api_version}/graphql.json"]
