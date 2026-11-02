from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the SendOwl API docs (https://dashboard.sendowl.com/developers).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "products": {
        "description": "A SendOwl product — a digital item, bundle, subscription, or drip content available for sale.",
        "docs_url": "https://dashboard.sendowl.com/developers/api/products",
        "columns": {
            "id": "The unique ID of the product.",
            "name": "The display name of the product.",
            "product_type": "The type of product (e.g. digital, bundle, subscription, drip).",
            "price": "The price of the product.",
            "currency_code": "The ISO currency code the product is priced in.",
            "sales_page_url": "The hosted sales/checkout page URL for the product.",
            "instant_buy_url": "The direct add-to-cart/instant-buy URL for the product.",
            "add_to_cart_url": "The add-to-cart URL for the product.",
            "created_at": "The date and time the product was created.",
            "updated_at": "The date and time the product was last updated.",
        },
    },
    "orders": {
        "description": "A SendOwl order — a completed purchase, including buyer, line items, and payment details.",
        "docs_url": "https://dashboard.sendowl.com/developers/api/orders",
        "columns": {
            "id": "The unique ID of the order.",
            "state": "The current state of the order (e.g. completed, refunded).",
            "buyer_email": "The email address of the buyer.",
            "buyer_name": "The name of the buyer.",
            "settled_currency": "The currency the order settled in.",
            "settled_gross": "The gross amount of the order in the settled currency.",
            "settled_tax": "The tax amount of the order in the settled currency.",
            "cart": "The cart contents — the line items purchased in this order.",
            "discount_code": "The discount code applied to the order, if any.",
            "created_at": "The date and time the order was created.",
            "updated_at": "The date and time the order was last updated.",
        },
    },
    "subscriptions": {
        "description": "A SendOwl subscription — a recurring purchase of a subscription product by a customer.",
        "docs_url": "https://dashboard.sendowl.com/developers/api/subscriptions",
        "columns": {
            "id": "The unique ID of the subscription.",
            "state": "The current state of the subscription (e.g. active, cancelled, expired).",
            "product_id": "The ID of the subscription product.",
            "buyer_email": "The email address of the subscriber.",
            "buyer_name": "The name of the subscriber.",
            "created_at": "The date and time the subscription was created.",
            "updated_at": "The date and time the subscription was last updated.",
        },
    },
    "discount_codes": {
        "description": "A SendOwl discount code — a coupon that applies a discount at checkout.",
        "docs_url": "https://dashboard.sendowl.com/developers/api/discount_codes",
        "columns": {
            "id": "The unique ID of the discount code.",
            "code": "The discount code string entered by buyers at checkout.",
            "discount_type": "The type of discount (e.g. percentage, fixed amount).",
            "percentage": "The percentage discount applied, when the type is percentage-based.",
            "amount": "The fixed amount discounted, when the type is amount-based.",
            "usage_count": "The number of times the code has been used.",
            "usage_limit": "The maximum number of times the code may be used.",
            "expiry_date": "The date the discount code expires.",
            "created_at": "The date and time the discount code was created.",
            "updated_at": "The date and time the discount code was last updated.",
        },
    },
}
