"""Canonical, documentation-sourced descriptions for Shopify endpoints and columns.

Sourced from the official Shopify Admin GraphQL API reference (https://shopify.dev/docs/api/admin-graphql).
Keyed by the schema names that `get_schemas` returns (the GraphQL object's `display_name or name`
from `constants.py` `SHOPIFY_GRAPHQL_OBJECTS`), which match the `ExternalDataSchema.name` of a synced
Shopify table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Shopify GraphQL objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Globally unique identifier for the object (a Shopify GraphQL GID).",
    "created_at": "Date and time when the object was created.",
    "updated_at": "Date and time when the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "abandonedCheckouts": {
        "description": "A checkout a customer started but did not complete, leaving items in their cart.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/AbandonedCheckout",
        "columns": _columns(
            abandoned_checkout_url="URL the customer can use to recover and complete the abandoned checkout.",
            total_price_set="Total price of the checkout, in shop and presentment currencies.",
            subtotal_price_set="Subtotal of the line items before taxes and shipping.",
            total_tax_set="Total tax charged on the checkout.",
            line_items="The products and quantities the customer added to the abandoned checkout.",
            customer="The customer associated with the abandoned checkout.",
            completed_at="Date and time when the checkout was completed, if it ever was.",
        ),
    },
    "articles": {
        "description": "A blog post (article) published to one of the shop's online store blogs.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/Article",
        "columns": _columns(
            title="The article's title.",
            handle="URL-friendly unique handle for the article.",
            body="The article's content, in HTML.",
            summary="Short summary of the article.",
            author="The author of the article.",
            blog="The blog the article belongs to.",
            tags="List of tags applied to the article.",
            is_published="Whether the article is visible on the online store.",
            published_at="Date and time when the article was published.",
        ),
    },
    "blogs": {
        "description": "A blog on the shop's online store that groups together articles.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/Blog",
        "columns": _columns(
            title="The blog's title.",
            handle="URL-friendly unique handle for the blog.",
            tags="List of tags used across the blog's articles.",
        ),
    },
    "catalogs": {
        "description": "A catalog that maps a set of products and prices to a market, company location, or app.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/interfaces/Catalog",
        "columns": _columns(
            title="The catalog's title.",
            status="Status of the catalog (e.g. ACTIVE, ARCHIVED, DRAFT).",
            price_list="The price list associated with the catalog.",
        ),
    },
    "collections": {
        "description": "A grouping of products that can be displayed and merchandised together in the store.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/Collection",
        "columns": _columns(
            title="The collection's title.",
            handle="URL-friendly unique handle for the collection.",
            description="The collection's description, as plain text.",
            description_html="The collection's description, in HTML.",
            products_count="Number of products in the collection.",
            sort_order="The order in which products in the collection are displayed.",
        ),
    },
    "customers": {
        "description": "A customer of the shop, holding contact details and order history.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/Customer",
        "columns": _columns(
            first_name="The customer's first name.",
            last_name="The customer's last name.",
            display_name="The customer's full name, formatted for display.",
            email="The customer's email address.",
            phone="The customer's phone number, in E.164 format.",
            number_of_orders="Number of orders the customer has placed.",
            amount_spent="Total amount the customer has spent across all orders.",
            state="The customer's account state (e.g. ENABLED, DISABLED, INVITED, DECLINED).",
            verified_email="Whether the customer has verified their email address.",
            tags="List of tags applied to the customer.",
            default_address="The customer's default mailing address.",
            note="Free-form note attached to the customer.",
            metafields="Custom metadata attached to the customer as metafields.",
        ),
    },
    "discountCodes": {
        "description": "A discount and its application rules — a code or automatic discount applied at checkout.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/DiscountNode",
        "columns": _columns(
            discount="The underlying discount object, with its type, value, and eligibility rules.",
        ),
    },
    "orders": {
        "description": "A customer's completed request to purchase one or more products from the shop.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/Order",
        "columns": _columns(
            name="The order's identifier, shown to the merchant and customer (e.g. #1001).",
            email="Email address associated with the order.",
            phone="Phone number associated with the order.",
            customer="The customer who placed the order.",
            display_financial_status="Financial status of the order (e.g. PAID, PENDING, REFUNDED, VOIDED).",
            display_fulfillment_status="Fulfillment status of the order (e.g. FULFILLED, UNFULFILLED, PARTIALLY_FULFILLED).",
            current_total_price_set="Current total price of the order, in shop and presentment currencies.",
            total_price_set="Total price of the order at the time it was placed.",
            subtotal_price_set="Sum of line item prices before taxes, shipping, and discounts.",
            total_tax_set="Total tax charged on the order.",
            total_discounts_set="Total value of discounts applied to the order.",
            line_items="The products and quantities purchased in the order.",
            shipping_address="The address the order is shipped to.",
            billing_address="The address used for billing.",
            cancelled_at="Date and time when the order was cancelled, if it was.",
            cancel_reason="Reason the order was cancelled, if applicable.",
            test="Whether the order is a test order.",
            tags="List of tags applied to the order.",
        ),
    },
    "products": {
        "description": "A product the shop sells, grouping its variants, media, and selling details.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/Product",
        "columns": _columns(
            title="The product's title.",
            handle="URL-friendly unique handle for the product.",
            description="The product's description, as plain text.",
            description_html="The product's description, in HTML.",
            product_type="The merchant-defined type of the product.",
            vendor="The product's vendor.",
            status="The product's status (ACTIVE, ARCHIVED, or DRAFT).",
            tags="List of tags applied to the product.",
            total_inventory="Total quantity of the product in stock across all variants.",
            price_range_v2="Minimum and maximum variant prices for the product.",
            variants="The product's variants (combinations of options like size and color).",
            published_at="Date and time when the product was published to the online store.",
        ),
    },
}
