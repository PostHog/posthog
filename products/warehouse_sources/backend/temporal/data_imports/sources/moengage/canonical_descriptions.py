from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_REPORT_COLUMNS = {
    "id": "Surrogate key hashed from the row's identity dimensions.",
    "campaign_id": "Identifier of the campaign the stats belong to.",
    "platform": "Platform the users engaged on (for example ANDROID, IOS, WEB).",
    "locale": "Locale breakdown of the stats, or all_locales for the campaign total.",
    "variation": "Campaign variation the stats belong to, or all_variations for the campaign total. Control groups appear as campaign_control_group and global_control_group.",
    "attempted": "Number of messages MoEngage attempted to send.",
    "sent": "Number of messages sent.",
    "failed": "Number of messages that failed to send.",
    "impression": "Number of impressions recorded for the campaign.",
    "click": "Number of clicks recorded for the campaign.",
    "ctr": "Click-through rate for the campaign.",
    "delivery_rate": "Share of attempted messages that were delivered.",
    "sent_rate": "Share of attempted messages that were sent.",
    "failure_rate": "Share of attempted messages that failed.",
    "conversion_goal_stats": "Conversions, conversion rate, and uplift per configured conversion goal.",
    "delivery_funnel": "Delivery funnel counts, from reachable users in the segment through to impressions.",
    "failure_breakdown": "Failure counts broken down by reason.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "Campaigns in the MoEngage workspace, across channels, with their status, delivery type, and configuration details.",
        "docs_url": "https://www.moengage.com/docs/api/get-campaign-details/search-campaigns-v5",
        "columns": {
            "id": "Unique identifier of the campaign document. With campaign versioning enabled, each published revision has its own id.",
            "campaign_id": "Stable campaign identifier shared by every version of the campaign.",
            "status": "Current status of the campaign (for example ACTIVE, SCHEDULED, STOPPED).",
            "channel": "Channel the campaign sends on (PUSH, EMAIL, or SMS).",
            "campaign_delivery_type": "How the campaign is delivered (for example ONE_TIME, PERIODIC, EVENT_TRIGGERED).",
            "created_by": "Email address of the user who created the campaign.",
            "created_at": "When the campaign was created, in the workspace timezone.",
            "updated_at": "When the campaign was last updated, in the workspace timezone.",
            "basic_details": "Campaign name, platforms, tags, and other channel-specific setup details.",
            "connector": "Delivery connector the campaign sends through (for example the email provider).",
        },
    },
    "campaign_report": {
        "description": "Per-campaign performance stats aggregated over the trailing 30 days, broken down by platform, locale, and variation. The whole table refreshes on every sync.",
        "docs_url": "https://www.moengage.com/docs/api/stats-report",
        "columns": {
            **_REPORT_COLUMNS,
            "start_date": "First day of the reported window.",
            "end_date": "Last day of the reported window.",
        },
    },
    "daily_campaign_report": {
        "description": "Per-campaign performance stats for a single day, broken down by platform, locale, and variation. One row per campaign, day, platform, locale, and variation.",
        "docs_url": "https://www.moengage.com/docs/api/stats-report",
        "columns": {
            **_REPORT_COLUMNS,
            "date": "Day the stats cover, in the workspace timezone.",
        },
    },
}
