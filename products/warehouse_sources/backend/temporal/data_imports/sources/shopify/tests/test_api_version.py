from datetime import date
from typing import Any

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import VersionDeprecation
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shopify import (
    ShopifyAuthMethodConfig,
    ShopifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.constants import (
    ORDERS,
    SHOPIFY_API_VERSION_2025_10,
    SHOPIFY_API_VERSION_2026_07,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source import ShopifySource

TOKEN_PATH = "/admin/oauth/access_token"


def _config() -> ShopifySourceConfig:
    return ShopifySourceConfig(
        shopify_store_id="my-store",
        auth_method=ShopifyAuthMethodConfig(
            selection="client_credentials", shopify_client_id="client-id", shopify_client_secret="secret"
        ),
    )


def _shopify(request: RecordedRequest) -> ScriptedResponse:
    if request.path == TOKEN_PATH:
        return ScriptedResponse(json={"access_token": "test-token"})
    if request.method == "GET":
        return ScriptedResponse(json={"access_scopes": []})
    return ScriptedResponse(
        json={"data": {ORDERS: {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
    )


def _graphql_urls(requests: list[RecordedRequest]) -> list[str]:
    return [request.url for request in requests if request.path.endswith("/graphql.json")]


class TestApiVersionResolution:
    def test_both_versions_are_supported(self) -> None:
        # The default flip is covered by the (None -> 2026-07) resolution case below; this only
        # guards that the legacy version stays declared alongside the new one.
        assert set(ShopifySource.supported_versions) == {SHOPIFY_API_VERSION_2025_10, SHOPIFY_API_VERSION_2026_07}

    def test_2025_10_is_deprecated_with_its_sunset_date(self) -> None:
        # The in-product deprecation warning and the repin migration both key off this metadata,
        # and the registry invariant test only checks generic invariants.
        assert ShopifySource.deprecated_versions == (
            VersionDeprecation(version=SHOPIFY_API_VERSION_2025_10, sunset_at=date(2026, 10, 16)),
        )

    @pytest.mark.parametrize(
        "pin, deprecated",
        [
            (SHOPIFY_API_VERSION_2025_10, True),
            (SHOPIFY_API_VERSION_2026_07, False),
            # An unpinned source resolves to the default, which is never deprecated.
            (None, False),
        ],
    )
    def test_deprecation_lookup_per_pin(self, pin: str | None, deprecated: bool) -> None:
        assert (ShopifySource().get_version_deprecation(pin) is not None) == deprecated

    @pytest.mark.parametrize(
        "pin, expected",
        [
            (SHOPIFY_API_VERSION_2025_10, SHOPIFY_API_VERSION_2025_10),
            (SHOPIFY_API_VERSION_2026_07, SHOPIFY_API_VERSION_2026_07),
            # An unpinned source resolves to the current default rather than the legacy version.
            (None, SHOPIFY_API_VERSION_2026_07),
        ],
    )
    def test_resolved_pin_reaches_request_layer(self, pin: str | None, expected: str) -> None:
        result = SourceDriver(ShopifySource(), _config()).run(ORDERS, _shopify, api_version=pin)

        assert result.raised is None
        assert _graphql_urls(result.requests) == [f"https://my-store.myshopify.com/admin/api/{expected}/graphql.json"]


class TestApiVersionReachesRequestUrl:
    @pytest.mark.parametrize("api_version", [SHOPIFY_API_VERSION_2025_10, SHOPIFY_API_VERSION_2026_07])
    def test_version_is_the_url_segment(self, api_version: str) -> None:
        result = SourceDriver(ShopifySource(), _config()).run(ORDERS, _shopify, api_version=api_version)

        assert result.raised is None
        assert _graphql_urls(result.requests) == [
            f"https://my-store.myshopify.com/admin/api/{api_version}/graphql.json"
        ]


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
            shopify_store_id="my-store",
            auth_method=ShopifyAuthMethodConfig(
                selection="client_credentials", shopify_client_id="id", shopify_client_secret="secret"
            ),
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
            shopify_store_id="my-store",
            auth_method=ShopifyAuthMethodConfig(
                selection="client_credentials", shopify_client_id="id", shopify_client_secret="secret"
            ),
        )

        ShopifySource().get_endpoint_permissions(config, team_id=1, endpoints=[ORDERS], api_version=pin)

        assert mock_check.call_args.args[-1] == expected

    @pytest.mark.parametrize("api_version", [SHOPIFY_API_VERSION_2025_10, SHOPIFY_API_VERSION_2026_07])
    def test_authenticated_session_url_carries_version(self, api_version: str) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
            _authenticated_session,
        )

        with scripted_network(_shopify):
            api_url, _ = _authenticated_session("my-store", "id", "secret", api_version)

        assert api_url == f"https://my-store.myshopify.com/admin/api/{api_version}/graphql.json"
