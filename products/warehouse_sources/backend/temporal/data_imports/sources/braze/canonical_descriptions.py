"""Canonical, documentation-sourced descriptions for Braze endpoints and columns.

Sourced from the official Braze REST API reference (https://www.braze.com/docs/api/endpoints/).
Keyed by the endpoint names in `settings.py` `BRAZE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Braze table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "A Braze messaging campaign that sends content to users across one or more channels.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/export/campaigns/get_campaigns/",
        "columns": {
            "id": "Unique identifier of the campaign.",
            "name": "Name of the campaign.",
            "is_api_campaign": "Whether the campaign is sent via the API.",
            "tags": "Tags associated with the campaign.",
            "last_edited": "Time at which the campaign was last edited.",
        },
    },
    "canvases": {
        "description": "A Braze Canvas — a multi-step customer journey across channels and time.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/export/canvas/get_canvases/",
        "columns": {
            "id": "Unique identifier of the Canvas.",
            "name": "Name of the Canvas.",
            "tags": "Tags associated with the Canvas.",
            "last_edited": "Time at which the Canvas was last edited.",
        },
    },
    "segments": {
        "description": "A Braze segment — a saved group of users defined by filter criteria.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/export/segments/get_segment/",
        "columns": {
            "id": "Unique identifier of the segment.",
            "name": "Name of the segment.",
            "analytics_tracking_enabled": "Whether analytics tracking is enabled for the segment.",
            "tags": "Tags associated with the segment.",
        },
    },
    "events": {
        "description": "The list of custom event names recorded in the Braze workspace.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/export/custom_events/get_custom_events/",
        "columns": {
            "event_name": "Name of the custom event.",
        },
    },
    "email_templates": {
        "description": "A reusable email template stored in Braze.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/templates/email_templates/get_list_email_templates/",
        "columns": {
            "email_template_id": "Unique identifier of the email template.",
            "template_name": "Name of the email template.",
            "created_at": "Time at which the template was created.",
            "updated_at": "Time at which the template was last updated.",
            "tags": "Tags associated with the template.",
        },
    },
    "content_blocks": {
        "description": "A reusable Content Block — a snippet of content shared across Braze messages.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/templates/content_blocks_templates/get_list_email_content_blocks/",
        "columns": {
            "content_block_id": "Unique identifier of the Content Block.",
            "name": "Name of the Content Block.",
            "content_type": "Type of the Content Block content (e.g. html, text).",
            "tags": "Tags associated with the Content Block.",
            "created_at": "Time at which the Content Block was created.",
            "last_edited": "Time at which the Content Block was last edited.",
        },
    },
}
