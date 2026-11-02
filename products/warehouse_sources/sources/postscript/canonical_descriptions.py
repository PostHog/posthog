from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "subscribers": {
        "description": "A person who has been collected into your Postscript shop, with their contact details, subscription status, and custom properties.",
        "docs_url": "https://developers.postscript.io/reference/get-subscribers",
        "columns": {
            "id": "Unique identifier for the subscriber.",
            "created_at": "When the subscriber was created, in ISO 8601 format.",
            "updated_at": "When the subscriber was last updated, in ISO 8601 format.",
            "email": "The subscriber's email address.",
            "phone_number": "The subscriber's phone number.",
            "ps_id": "Postscript tracking ID for the subscriber, also stored in the ps_id cookie on the storefront.",
            "shopify_customer_id": "Identifier of the matching customer in the connected Shopify store.",
            "properties": "Built-in subscriber properties Postscript maintains, such as has_purchased, days_since_purchase, categories, and birthday.",
            "subscriptions": "Per-channel sending permission, with a can_send flag for promotional and transactional messaging.",
            "tags": "Tags applied to the subscriber.",
            "data": "Custom subscriber properties set on the subscriber.",
        },
    },
    "keywords": {
        "description": "An active keyword for your shop that people can text in to subscribe or trigger an automation.",
        "docs_url": "https://developers.postscript.io/reference/get-keywords",
        "columns": {
            "id": "Unique identifier for the keyword.",
            "keyword": "The word people text in to trigger this keyword.",
            "triggered_count": "How many times the keyword has been triggered.",
            "created_at": "When the keyword was created, in ISO 8601 format.",
            "updated_at": "When the keyword was last updated, in ISO 8601 format.",
        },
    },
}
