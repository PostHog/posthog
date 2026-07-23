from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shopify import (
    ShopifySourceConfig,
)
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
    def test_both_versions_are_supported(self) -> None:
        # The default flip is covered by the (None -> 2026-07) resolution case below; this only
        # guards that the legacy version stays declared alongside the new one.
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


class TestNonSyncSurfacesUseResolvedPin:
    """Credential validation and permission probes carry the version in the URL too, so a pinned
    source must probe under its own pin — not the current default."""

    @pytest.mark.parametrize(
        "pin, expected",
        [
            (SHOPIFY_API_VERSION_2025_10, SHOPIFY_API_VERSION_2025_10),
            (SHOPIFY_API_VERSION_2026_07, SHOPIFY_API_VERSION_2026_07),
            (None, SHOPIFY_API_VERSION_2026_07),
        ],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source.validate_shopify_credentials"
    )
    def test_validate_credentials_passes_resolved_pin(self, mock_validate: Any, pin: str | None, expected: str) -> None:
        mock_validate.return_value = True
        config = ShopifySourceConfig(
            shopify_store_id="my-store", shopify_client_id="id", shopify_client_secret="secret"
        )

        ShopifySource().validate_credentials(config, team_id=1, api_version=pin)

        assert mock_validate.call_args.args[-1] == expected

    @pytest.mark.parametrize(
        "pin, expected",
        [
            (SHOPIFY_API_VERSION_2025_10, SHOPIFY_API_VERSION_2025_10),
            (None, SHOPIFY_API_VERSION_2026_07),
        ],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source.check_shopify_endpoint_permissions"
    )
    def test_endpoint_permissions_pass_resolved_pin(self, mock_check: Any, pin: str | None, expected: str) -> None:
        mock_check.return_value = {}
        config = ShopifySourceConfig(
            shopify_store_id="my-store", shopify_client_id="id", shopify_client_secret="secret"
        )

        ShopifySource().get_endpoint_permissions(config, team_id=1, endpoints=[ORDERS], api_version=pin)

        assert mock_check.call_args.args[-1] == expected

    @pytest.mark.parametrize("api_version", [SHOPIFY_API_VERSION_2025_10, SHOPIFY_API_VERSION_2026_07])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify._get_shopify_access_token")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify.make_tracked_session")
    def test_authenticated_session_url_carries_version(self, session_cls: Any, token: Any, api_version: str) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
            _authenticated_session,
        )

        token.return_value = "tok"
        api_url, _ = _authenticated_session("my-store", "id", "secret", api_version)

        assert api_url == f"https://my-store.myshopify.com/admin/api/{api_version}/graphql.json"
