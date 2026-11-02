import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
    SHOPIFY_INVALID_STORE_ID_ERROR,
    _get_shopify_access_token,
    normalize_store_id,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("my-store", "my-store"),
        ("MY-STORE", "my-store"),
        ("  my-store  ", "my-store"),
        ("my-store.myshopify.com", "my-store"),
        ("https://my-store.myshopify.com", "my-store"),
        ("http://my-store.myshopify.com/", "my-store"),
        ("my-store.myshopify.com/admin/api", "my-store"),
        ("https://admin.shopify.com/store/my-store", "my-store"),
        ("https://admin.shopify.com/store/my-store/products", "my-store"),
        # Accidental double suffix collapses back to the bare subdomain.
        ("my-store.myshopify.com.myshopify.com", "my-store"),
        # A trailing dot (FQDN form) is tolerated rather than rejected.
        ("my-store.myshopify.com.", "my-store"),
        ("https://my-store.myshopify.com./", "my-store"),
        ("store123", "store123"),
    ],
)
def test_normalize_store_id_accepts_common_paste_forms(raw, expected):
    assert normalize_store_id(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "https://evil.com",
        "shop.example.com",
        "my_store",
        "store with spaces",
        "-leading-hyphen",
    ],
)
def test_normalize_store_id_rejects_invalid(raw):
    with pytest.raises(ValueError) as exc_info:
        normalize_store_id(raw)
    assert str(exc_info.value) == SHOPIFY_INVALID_STORE_ID_ERROR


def test_access_token_url_has_no_doubled_suffix_for_messy_input():
    with scripted_network([ScriptedResponse(json={"access_token": "shpat_x"})]) as network:
        # Callers normalize before threading the store id through, so messy input has
        # already collapsed to the bare subdomain by the time it reaches this function.
        _get_shopify_access_token(normalize_store_id("https://my-store.myshopify.com"), "client-id", "client-secret")

    assert [request.url for request in network.requests_log] == [
        "https://my-store.myshopify.com/admin/oauth/access_token"
    ]
