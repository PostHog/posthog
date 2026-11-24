from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "Occurrences of the configured CleverTap event within the export date range.",
        "docs_url": "https://developer.clevertap.com/docs/get-events-api",
        "columns": {
            "event_name": "The event name selected for this connection.",
            "ts": "Event time in account time, stored as a YYYYMMDDHHMMSS integer.",
            "event_date": "The event date in account time, derived from ts for stable partitioning.",
            "profile": "User identifiers, platform, and profile properties associated with this event.",
            "events": "Event summaries returned by CleverTap for this user.",
            "event_props": "Properties associated with this event occurrence.",
            "session_props": "Session metadata and campaign attribution properties.",
        },
    },
    "profiles": {
        "description": "Profiles of users who performed the configured event within the export date range.",
        "docs_url": "https://developer.clevertap.com/docs/get-user-profiles-api",
        "columns": {
            "identity": "The custom user identifier, when the account has assigned one.",
            "email": "The user email address, when available.",
            "name": "The user name, when available.",
            "profileData": "Custom profile properties and channel subscription preferences.",
            "platformInfo": "Device and platform metadata, including platform object IDs.",
            "events": "Lifetime event counts and the first and last occurrence times for each event.",
        },
    },
    "message_reports": {
        "description": "Messages that CleverTap started within the export date range, with delivery metrics.",
        "docs_url": "https://developer.clevertap.com/docs/get-message-reports-api",
        "columns": {
            "message_id": "Unique identifier for the message.",
            "message_name": "The name of the campaign.",
            "data": "Delivery metrics (sent, viewed, clicked), aggregated over the date range.",
            "start_date": "The campaign start date and time, without the year (for example, Oct 18, 4:08 PM).",
            "device": "Platforms targeted by the campaign.",
            "conversion_event": "The event configured as the conversion goal, or null.",
            "labels": "Labels assigned to the campaign.",
            "status": "Current status of the campaign: scheduled, running, stopped, or completed.",
            "channel": "The channel used by the campaign, as a display name (for example, InApp).",
            "delivery": "The delivery type of the campaign, as a display name.",
        },
    },
    "campaigns": {
        "description": "Campaigns created through the CleverTap API and scheduled within the export date range.",
        "docs_url": "https://developer.clevertap.com/docs/get-campaigns-api",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "name": "Name of the campaign as specified at creation.",
            "scheduled_on": "Scheduled date and time in account time, stored as a YYYYMMDDHHMM integer.",
            "status": "Current status: scheduled, pending, running, paused, stopped, or completed.",
        },
    },
    "campaign_reports": {
        "description": "Delivery and click metrics for each completed campaign created through the CleverTap API.",
        "docs_url": "https://developer.clevertap.com/docs/get-campaign-report-api",
        "columns": {
            "campaign_id": "Identifier of the campaign this report belongs to.",
            "campaign_name": "Name of the campaign.",
            "scheduled_on": "Scheduled date and time of the campaign in account time, as a YYYYMMDDHHMM integer.",
            "sent": "Number of messages attempted to be sent.",
            "clicked": "Number of users who clicked the message.",
        },
    },
    "content_blocks": {
        "description": "Reusable blocks of content (text or HTML) that campaigns can share.",
        "docs_url": "https://developer.clevertap.com/docs/get-content-block-list-api",
        "columns": {
            "id": "Unique identifier for the content block.",
            "name": "Name of the content block.",
            "type": "Content type of the block: html or text.",
            "content": "The content of the block.",
            "createdBy": "Email address of the user who created the block.",
            "createdAt": "Time the block was created, in ISO 8601 format.",
            "updatedBy": "Email address of the user who last updated the block.",
            "updatedAt": "Time the block was last updated, in ISO 8601 format.",
        },
    },
}
