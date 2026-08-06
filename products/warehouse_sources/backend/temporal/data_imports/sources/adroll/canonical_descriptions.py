"""Canonical, documentation-sourced descriptions for AdRoll (NextRoll) endpoints and columns.

Sourced from the official NextRoll/AdRoll API reference (https://developers.nextroll.com/).
Keyed by the endpoint names in `settings.py` `ADROLL_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced AdRoll table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "advertisables": {
        "description": "An advertisable entity (a brand or product) under your AdRoll organization that campaigns run against.",
        "docs_url": "https://developers.nextroll.com/api-reference/index.html",
        "columns": {
            "eid": "Unique encoded identifier (EID) for the advertisable.",
            "name": "Display name of the advertisable.",
            "advertiser_id": "Identifier of the advertiser the advertisable belongs to.",
            "organization": "EID of the organization that owns the advertisable.",
            "status": "Current status of the advertisable (e.g. live, paused).",
            "created_date": "Time at which the advertisable was created.",
            "currency": "Three-letter ISO currency code used for the advertisable's spend.",
            "time_zone": "Time zone configured for the advertisable.",
        },
    },
    "campaigns": {
        "description": "An advertising campaign belonging to an advertisable, grouping ads toward a goal and budget.",
        "docs_url": "https://developers.nextroll.com/api-reference/index.html",
        "columns": {
            "eid": "Unique encoded identifier (EID) for the campaign.",
            "_advertisable_eid": "EID of the parent advertisable the campaign belongs to (added during sync).",
            "name": "Display name of the campaign.",
            "advertisable": "EID of the advertisable the campaign belongs to.",
            "status": "Current status of the campaign (e.g. live, paused, archived).",
            "budget": "Budget allocated to the campaign.",
            "start_date": "Date the campaign starts running.",
            "end_date": "Date the campaign stops running.",
            "created_date": "Time at which the campaign was created.",
            "channel": "Advertising channel the campaign runs on (e.g. web, social).",
            "type": "Type of the campaign (e.g. retargeting, prospecting).",
        },
    },
    "ads": {
        "description": "An individual ad creative belonging to an advertisable, served within campaigns.",
        "docs_url": "https://developers.nextroll.com/api-reference/index.html",
        "columns": {
            "eid": "Unique encoded identifier (EID) for the ad.",
            "_advertisable_eid": "EID of the parent advertisable the ad belongs to (added during sync).",
            "name": "Display name of the ad.",
            "advertisable": "EID of the advertisable the ad belongs to.",
            "status": "Current status of the ad (e.g. live, paused, rejected).",
            "ad_format_id": "Identifier of the ad format/size.",
            "width": "Width of the ad creative in pixels.",
            "height": "Height of the ad creative in pixels.",
            "created_date": "Time at which the ad was created.",
            "type": "Type of the ad creative (e.g. image, html5, native).",
            "clickthrough_url": "Destination URL the ad links to when clicked.",
        },
    },
}
