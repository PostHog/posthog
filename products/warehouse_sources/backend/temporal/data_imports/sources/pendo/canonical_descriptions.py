"""Canonical, documentation-sourced descriptions for Pendo endpoints and columns.

Sourced from the official Pendo API reference (https://engageapi.pendo.io). Keyed by the endpoint
names in `settings.py` `PENDO_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
Pendo table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "features": {
        "description": "A tagged UI element (button, link, etc.) whose usage Pendo tracks within your application.",
        "docs_url": "https://engageapi.pendo.io/#a55c1ce4-1e9c-4e64-a78e-fc824ade8edd",
        "columns": {
            "id": "Unique identifier for the feature.",
            "name": "The feature's display name.",
            "appId": "ID of the application the feature belongs to.",
            "kind": "The kind of element the feature tags (e.g. button, link).",
            "group": "The product area or group the feature is organized under.",
            "createdAt": "Time at which the feature was created, as a Unix timestamp in milliseconds.",
            "lastUpdatedAt": "Time at which the feature was last updated, as a Unix timestamp in milliseconds.",
            "createdByUser": "The user who created the feature.",
            "lastUpdatedByUser": "The user who last updated the feature.",
            "color": "Display color assigned to the feature in Pendo.",
            "dirty": "Whether the feature's processing data is stale and being recomputed.",
        },
    },
    "pages": {
        "description": "A tagged page or screen in your application whose views Pendo tracks.",
        "docs_url": "https://engageapi.pendo.io/#a55c1ce4-1e9c-4e64-a78e-fc824ade8edd",
        "columns": {
            "id": "Unique identifier for the page.",
            "name": "The page's display name.",
            "appId": "ID of the application the page belongs to.",
            "group": "The product area or group the page is organized under.",
            "rules": "URL matching rules that define which URLs map to this page.",
            "createdAt": "Time at which the page was created, as a Unix timestamp in milliseconds.",
            "lastUpdatedAt": "Time at which the page was last updated, as a Unix timestamp in milliseconds.",
            "createdByUser": "The user who created the page.",
            "lastUpdatedByUser": "The user who last updated the page.",
            "color": "Display color assigned to the page in Pendo.",
            "dirty": "Whether the page's processing data is stale and being recomputed.",
        },
    },
    "guides": {
        "description": "An in-app message or walkthrough shown to users, such as a tooltip, banner, or lightbox.",
        "docs_url": "https://engageapi.pendo.io/#a55c1ce4-1e9c-4e64-a78e-fc824ade8edd",
        "columns": {
            "id": "Unique identifier for the guide.",
            "name": "The guide's name.",
            "appId": "ID of the application the guide is shown in.",
            "state": "The guide's lifecycle state (e.g. draft, public, disabled).",
            "createdAt": "Time at which the guide was created, as a Unix timestamp in milliseconds.",
            "lastUpdatedAt": "Time at which the guide was last updated, as a Unix timestamp in milliseconds.",
            "createdByUser": "The user who created the guide.",
            "lastUpdatedByUser": "The user who last updated the guide.",
            "publishedAt": "Time at which the guide was published, as a Unix timestamp in milliseconds.",
            "launchMethod": "How the guide is launched (e.g. automatic, badge, dom).",
            "audienceUiHint": "Description of the segment the guide is targeted to.",
        },
    },
    "visitors": {
        "description": "An individual end user of your application, identified by a visitor ID, with their metadata.",
        "docs_url": "https://engageapi.pendo.io/#5a695fb5-3da2-4a0e-9bbd-c7b276dbc4b8",
        "columns": {
            "visitorId": "Unique identifier for the visitor.",
            "metadata": "Custom and agent-collected metadata fields attached to the visitor.",
        },
    },
    "accounts": {
        "description": "An organization or account that groups visitors together, with its metadata.",
        "docs_url": "https://engageapi.pendo.io/#5a695fb5-3da2-4a0e-9bbd-c7b276dbc4b8",
        "columns": {
            "accountId": "Unique identifier for the account.",
            "metadata": "Custom and agent-collected metadata fields attached to the account.",
        },
    },
}
