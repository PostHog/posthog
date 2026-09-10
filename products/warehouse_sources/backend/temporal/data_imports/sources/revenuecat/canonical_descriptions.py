"""Canonical, documentation-sourced descriptions for RevenueCat endpoints and columns.

Sourced from the official RevenueCat API v2 reference (https://www.revenuecat.com/docs/api-v2)
and the webhook event reference (https://www.revenuecat.com/docs/integrations/webhooks/event-types-and-fields).
Keyed by the resource names in `constants.py`, which match the `ExternalDataSchema.name` of a
synced RevenueCat table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.constants import (
    APP_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    ENTITLEMENT_RESOURCE_NAME,
    EVENT_RESOURCE_NAME,
    OFFERING_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
)

# Fields shared by most RevenueCat v2 objects.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "object": "String describing the object's RevenueCat type (e.g. 'product', 'entitlement').",
    "project_id": "ID of the RevenueCat project the object belongs to.",
    "created_at": "Time at which the object was created (Unix seconds).",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    CUSTOMER_RESOURCE_NAME: {
        "description": "An end user of the app, identified by their RevenueCat App User ID.",
        "docs_url": "https://www.revenuecat.com/docs/api-v2#tag/Customer",
        "columns": {
            "id": "The customer's RevenueCat App User ID.",
            "object": "String describing the object's type ('customer').",
            "project_id": "ID of the RevenueCat project the customer belongs to.",
            "first_seen_at": "Time at which the customer was first seen (Unix seconds).",
            "last_seen_at": "Time at which the customer was most recently seen.",
            "active_entitlements": "The customer's currently active entitlements.",
            "experiment": "The experiment the customer is enrolled in, if any.",
            "attributes": "Custom attributes set on the customer.",
        },
    },
    PRODUCT_RESOURCE_NAME: {
        "description": "A purchasable product (subscription or one-time purchase) configured in RevenueCat.",
        "docs_url": "https://www.revenuecat.com/docs/api-v2#tag/Product",
        "columns": _columns(
            store_identifier="The product identifier in its store (e.g. App Store, Play Store).",
            type="Type of product (subscription or one_time).",
            display_name="Human-readable display name of the product.",
            app_id="ID of the app the product belongs to.",
            subscription="Subscription configuration for the product, if it is a subscription.",
            one_time="One-time purchase configuration for the product, if it is a one-time purchase.",
        ),
    },
    ENTITLEMENT_RESOURCE_NAME: {
        "description": "A level of access (entitlement) that products can unlock for customers.",
        "docs_url": "https://www.revenuecat.com/docs/api-v2#tag/Entitlement",
        "columns": _columns(
            lookup_key="Your unique key identifying the entitlement.",
            display_name="Human-readable display name of the entitlement.",
            products="Products that grant this entitlement.",
        ),
    },
    OFFERING_RESOURCE_NAME: {
        "description": "A configured set of packages presented to customers as purchase options.",
        "docs_url": "https://www.revenuecat.com/docs/api-v2#tag/Offering",
        "columns": _columns(
            lookup_key="Your unique key identifying the offering.",
            display_name="Human-readable display name of the offering.",
            is_current="Whether this is the current default offering.",
            packages="Packages contained in the offering.",
        ),
    },
    APP_RESOURCE_NAME: {
        "description": "An app within a RevenueCat project, tied to a specific store platform.",
        "docs_url": "https://www.revenuecat.com/docs/api-v2#tag/App",
        "columns": _columns(
            name="The app's name.",
            type="The app's store platform (e.g. app_store, play_store, stripe).",
        ),
    },
    EVENT_RESOURCE_NAME: {
        "description": "A realtime webhook event capturing subscription and purchase activity.",
        "docs_url": "https://www.revenuecat.com/docs/integrations/webhooks/event-types-and-fields",
        "columns": {
            "id": "Unique identifier for the event.",
            "type": "The event type (e.g. INITIAL_PURCHASE, RENEWAL, CANCELLATION, EXPIRATION).",
            "app_user_id": "The RevenueCat App User ID the event is for.",
            "original_app_user_id": "The original App User ID before any aliasing.",
            "aliases": "All App User IDs aliased to this customer.",
            "product_id": "Identifier of the product involved in the event.",
            "entitlement_ids": "Entitlements affected by the event.",
            "store": "The store the purchase was made through (e.g. APP_STORE, PLAY_STORE).",
            "environment": "Whether the event is from PRODUCTION or SANDBOX.",
            "currency": "Three-letter ISO currency code of the transaction.",
            "price": "Price of the transaction.",
            "price_in_purchased_currency": "Price in the currency the purchase was made in.",
            "is_family_share": "Whether the purchase was shared via Family Sharing; always false outside the App Store.",
            "purchased_at_ms": "Time of the purchase, in milliseconds since epoch.",
            "expiration_at_ms": "Time the subscription expires, in milliseconds since epoch.",
            "event_timestamp_ms": "Time the event occurred, in milliseconds since epoch.",
            "created_at": "Time the event occurred (Unix seconds, derived from event_timestamp_ms).",
            "api_version": "RevenueCat webhook payload API version.",
        },
    },
}
