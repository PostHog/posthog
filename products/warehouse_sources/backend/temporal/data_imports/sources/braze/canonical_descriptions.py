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
    "campaign_analytics": {
        "description": "A daily series of send, engagement and conversion stats for one campaign.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/export/campaigns/get_campaign_analytics/",
        "columns": {
            "campaign_id": "Identifier of the campaign the row describes.",
            "time": "Date the stats cover, as an ISO 8601 date.",
            "unique_recipients": "Number of unique users who received a message from the campaign.",
            "revenue": "Revenue attributed to the campaign, in US dollars.",
            "conversions": "Conversions of the campaign's primary conversion event.",
            "conversions_by_send_time": "Primary conversions attributed to the date the campaign was sent.",
            "conversions1": "Conversions of the campaign's second conversion event.",
            "conversions2": "Conversions of the campaign's third conversion event.",
            "conversions3": "Conversions of the campaign's fourth conversion event.",
            "messages": "Per-channel, per-variation message stats, JSON-encoded because the channels present vary per campaign.",
        },
    },
    "canvas_analytics": {
        "description": "A daily series of entry, conversion and revenue stats for one Canvas.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/export/canvas/get_canvas_analytics/",
        "columns": {
            "canvas_id": "Identifier of the Canvas the row describes.",
            "canvas_name": "Name of the Canvas.",
            "time": "Date the stats cover, as an ISO 8601 date.",
            "entries": "Number of users who entered the Canvas.",
            "conversions": "Conversions of the Canvas's primary conversion event.",
            "conversions_by_entry_time": "Primary conversions attributed to the date the user entered the Canvas.",
            "revenue": "Revenue attributed to the Canvas, in US dollars.",
            "variant_stats": "Per-variant stats keyed by variant API identifier, JSON-encoded.",
            "step_stats": "Per-step stats and message stats keyed by step API identifier, JSON-encoded.",
        },
    },
    "event_analytics": {
        "description": "A daily series of how often one custom event occurred.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/export/custom_events/get_custom_events_analytics/",
        "columns": {
            "event_name": "Name of the custom event the row describes.",
            "time": "Date the count covers, as an ISO 8601 date.",
            "count": "Number of occurrences of the custom event.",
        },
    },
    "segment_analytics": {
        "description": "A daily series of the estimated size of one segment. Only segments with analytics tracking enabled are synced, because Braze keeps no size history for the others.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/export/segments/get_segment_analytics/",
        "columns": {
            "segment_id": "Identifier of the segment the row describes.",
            "time": "Date the size was measured on, as an ISO 8601 date.",
            "size": "Estimated number of users in the segment on this date.",
        },
    },
    "kpi_dau": {
        "description": "A daily series of the number of daily active users across the workspace.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/export/kpi/get_kpi_dau_date/",
        "columns": {
            "time": "Date the count covers, as an ISO 8601 date.",
            "dau": "Number of daily active users.",
        },
    },
    "kpi_mau": {
        "description": "A daily series of unique active users over a rolling 30-day window.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/export/kpi/get_kpi_mau_30_days/",
        "columns": {
            "time": "Date the rolling window ends on, as an ISO 8601 date.",
            "mau": "Number of unique active users in the 30 days ending on this date.",
        },
    },
    "kpi_new_users": {
        "description": "A daily series of the number of new users across the workspace.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/export/kpi/get_kpi_daily_new_users_date/",
        "columns": {
            "time": "Date the count covers, as an ISO 8601 date.",
            "new_users": "Number of new users first seen on this date.",
        },
    },
    "kpi_uninstalls": {
        "description": "A daily series of the number of app uninstalls across the workspace.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/export/kpi/get_kpi_uninstalls_date/",
        "columns": {
            "time": "Date the count covers, as an ISO 8601 date.",
            "uninstalls": "Number of uninstalls recorded on this date.",
        },
    },
    "campaign_details": {
        "description": "The full configuration of one campaign — its channels, message variants, tags and conversion behaviors.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/export/campaigns/get_campaign_details/",
        "columns": {
            "campaign_id": "Identifier of the campaign the row describes.",
            "created_at": "Time at which the campaign was created.",
            "updated_at": "Time at which the campaign was last updated.",
            "archived": "Whether the campaign is archived.",
            "draft": "Whether the campaign is a draft.",
            "enabled": "Whether the campaign is active.",
            "has_post_launch_draft": "Whether the campaign has a post-launch draft.",
            "name": "Name of the campaign.",
            "description": "Description of the campaign.",
            "schedule_type": "Type of scheduling action the campaign uses.",
            "channels": "Channels the campaign sends via.",
            "first_sent": "Date and hour the campaign first sent.",
            "last_sent": "Date and hour the campaign last sent.",
            "tags": "Tag names associated with the campaign.",
            "teams": "Names of the teams associated with the campaign.",
            "messages": "Message variants keyed by message variation identifier, JSON-encoded because the keys and channel-specific fields vary per campaign.",
            "conversion_behaviors": "Conversion event behaviors assigned to the campaign, JSON-encoded.",
        },
    },
    "canvas_details": {
        "description": "The full structure of one Canvas — its steps, variants, channels and tags.",
        "docs_url": "https://www.braze.com/docs/api/endpoints/export/canvas/get_canvas_details/",
        "columns": {
            "canvas_id": "Identifier of the Canvas the row describes.",
            "created_at": "Time at which the Canvas was created.",
            "updated_at": "Time at which the Canvas was last updated.",
            "name": "Name of the Canvas.",
            "description": "Description of the Canvas.",
            "archived": "Whether the Canvas is archived.",
            "draft": "Whether the Canvas is a draft.",
            "enabled": "Whether the Canvas is active.",
            "has_post_launch_draft": "Whether the Canvas has a post-launch draft.",
            "schedule_type": "Type of scheduling action the Canvas uses.",
            "first_entry": "Date of the first user entry into the Canvas.",
            "last_entry": "Date of the most recent user entry into the Canvas.",
            "channels": "Channels used by the Canvas steps.",
            "variants": "Canvas variants, each with its name, API identifier and first step identifiers, JSON-encoded.",
            "tags": "Tag names associated with the Canvas.",
            "teams": "Names of the teams associated with the Canvas.",
            "steps": "Canvas steps, each with its name, type, API identifier and next-step paths, JSON-encoded.",
        },
    },
}
