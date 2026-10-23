from products.warehouse_sources.backend.temporal.data_imports.sources.buy_me_a_coffee.settings import API_DOCS_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "supporters": {
        "description": "One-time support payments to the creator, including payer details and support messages.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "support_id": "Unique identifier of the support payment.",
            "support_created_on": "Time the support payment was created.",
            "support_updated_on": "Time the support payment was last updated.",
            "support_coffees": "Number of coffees purchased.",
            "support_coffee_price": "Price of one coffee in the payment currency.",
            "support_currency": "Currency of the support payment.",
            "is_refunded": "Whether the support payment was refunded.",
        },
    },
    "subscriptions": {
        "description": "Active and inactive creator memberships, including billing periods and payer details.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "subscription_id": "Unique identifier of the membership subscription.",
            "subscription_created_on": "Time the membership subscription was created.",
            "subscription_updated_on": "Time the membership subscription was last updated.",
            "subscription_cancelled_on": "Time the membership subscription was canceled, if applicable.",
            "subscription_currency": "Currency of the membership subscription.",
            "subscription_duration_type": "Billing duration of the membership subscription.",
        },
    },
    "extras": {
        "description": "Purchases of the creator's Extras, including amounts, payer details, and nested reward information.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "purchase_id": "Unique identifier of the Extras purchase.",
            "purchased_on": "Time the Extras purchase was made.",
            "purchase_updated_on": "Time the Extras purchase was last updated.",
            "purchase_amount": "Amount of the Extras purchase in its currency.",
            "purchase_currency": "Currency of the Extras purchase.",
            "purchase_is_revoked": "Whether access to the purchased Extra was revoked.",
            "extra": "Reward information associated with the purchase.",
        },
    },
}
