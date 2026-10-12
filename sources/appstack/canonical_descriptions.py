# Curated from the official Appstack Exports API reference: https://docs.appstack.tech/api/export
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "Attributed events for the connected app: installs and in-app events matched to the ad campaigns that drove them, one row per event.",
        "docs_url": "https://docs.appstack.tech/api/export",
        "columns": {
            "event_id": "Unique identifier for the event.",
            "event_time": "When the event occurred (ISO 8601). Exports are ordered by this field ascending.",
            "event_name": "Name of the event, prefixed by Appstack (e.g. appstack_purchase).",
            "appstack_id": "Appstack's identifier for the device/user the event belongs to.",
            "media_source": "Ad network or media source the event is attributed to.",
            "campaign_id": "Identifier of the attributed campaign.",
            "campaign_name": "Name of the attributed campaign.",
            "adset_id": "Identifier of the attributed ad set.",
            "adset_name": "Name of the attributed ad set.",
            "ad_id": "Identifier of the attributed ad.",
            "ad_name": "Name of the attributed ad.",
            "matching_type": "How the event was matched to the ad interaction: network or geo.",
            "click_to_first_open_hours": "Hours between the ad click and the app's first open.",
            "confidence_score": "Confidence of the attribution match: low, medium, or high.",
            "country": "Country of the device (ISO 3166-1 alpha-2).",
            "os": "Device operating system: ios or android.",
            "app_id": "Identifier of the app the event belongs to.",
            "app_name": "Name of the app the event belongs to.",
            "install_type": "iOS only: new_install or reinstall_same_device.",
            "revenue": "Revenue amount attached to the event, in the original currency; null for non-revenue events.",
            "currency": "Currency of the revenue amount (ISO 4217).",
            "revenue_usd": "Revenue converted to USD at the event-date exchange rate; null for non-revenue events.",
            "idfv": "iOS identifier for vendor, when available.",
            "maid": "Mobile advertising ID (GAID or IDFA), when available.",
            "customer_user_id": "Your own user identifier for the device/user, when set in the SDK.",
        },
    },
}
