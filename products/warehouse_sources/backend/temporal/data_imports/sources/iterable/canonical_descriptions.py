"""Canonical, documentation-sourced descriptions for Iterable endpoints and columns.

Sourced from the official Iterable API reference (https://api.iterable.com/api/docs). Keyed by the
endpoint names in `settings.py` `ITERABLE_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Iterable table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "A marketing campaign in Iterable that sends messages to a target audience.",
        "docs_url": "https://api.iterable.com/api/docs#campaigns_campaigns",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "name": "The campaign's name.",
            "templateId": "Identifier of the template used by the campaign.",
            "messageMedium": "The medium the campaign sends through (e.g. Email, Push, SMS).",
            "message_medium": "The medium the campaign sends through (e.g. Email, Push, SMS).",
            "campaignState": "Current state of the campaign (e.g. Draft, Ready, Running, Finished).",
            "type": "The campaign type (e.g. Blast, Triggered).",
            "listIds": "Identifiers of the lists the campaign sends to.",
            "suppressionListIds": "Identifiers of the lists suppressed from the campaign.",
            "labels": "Labels applied to the campaign.",
            "createdAt": "Time at which the campaign was created, as a Unix timestamp in milliseconds.",
            "updatedAt": "Time at which the campaign was last updated, as a Unix timestamp in milliseconds.",
            "startAt": "Scheduled send time of the campaign, as a Unix timestamp in milliseconds.",
            "endedAt": "Time at which the campaign finished sending, as a Unix timestamp in milliseconds.",
            "createdByUserId": "Identifier of the user who created the campaign.",
            "created_by_user_id": "Identifier of the user who created the campaign.",
            "sendSize": "Number of recipients the campaign was sent to.",
        },
    },
    "channels": {
        "description": "A messaging channel in Iterable that groups message types (e.g. a marketing or transactional channel).",
        "docs_url": "https://api.iterable.com/api/docs#channels_channels",
        "columns": {
            "id": "Unique identifier for the channel.",
            "name": "The channel's name.",
            "channelType": "The channel's type (e.g. Marketing, Transactional).",
            "messageMedium": "The medium the channel sends through (e.g. Email, Push, SMS).",
        },
    },
    "lists": {
        "description": "A list of subscribers in Iterable used to target messages.",
        "docs_url": "https://api.iterable.com/api/docs#lists_getLists",
        "columns": {
            "id": "Unique identifier for the list.",
            "name": "The list's name.",
            "description": "Description of the list.",
            "listType": "The list's type (e.g. Standard).",
            "createdAt": "Time at which the list was created, as a Unix timestamp.",
        },
    },
    "message_types": {
        "description": "A message type in Iterable, used for subscription management within a channel.",
        "docs_url": "https://api.iterable.com/api/docs#messageTypes_messageTypes",
        "columns": {
            "id": "Unique identifier for the message type.",
            "name": "The message type's name.",
            "channelId": "Identifier of the channel this message type belongs to.",
            "subscriptionPolicy": "The subscription policy (e.g. OptIn, OptOut).",
            "rateLimitPerMinute": "Maximum number of messages of this type sent per minute.",
            "frequencyCap": "Frequency cap applied to this message type.",
            "createdAt": "Time at which the message type was created, as a Unix timestamp.",
            "updatedAt": "Time at which the message type was last updated, as a Unix timestamp.",
        },
    },
    "templates": {
        "description": "A reusable message template in Iterable used by campaigns and triggered sends.",
        "docs_url": "https://api.iterable.com/api/docs#templates_getTemplates",
        "columns": {
            "templateId": "Unique identifier for the template.",
            "name": "The template's name.",
            "messageTypeId": "Identifier of the message type the template belongs to.",
            "creatorUserId": "Identifier of the user who created the template.",
            "clientTemplateId": "Client-assigned identifier for the template.",
            "createdAt": "Time at which the template was created, as a Unix timestamp.",
            "updatedAt": "Time at which the template was last updated, as a Unix timestamp.",
        },
    },
    "campaign_metrics": {
        "description": "Lifetime performance metrics for an Iterable campaign, such as sends, opens, clicks, bounces and unsubscribes.",
        "docs_url": "https://api.iterable.com/api/docs#campaigns_metrics",
        "columns": {
            "id": "Identifier of the campaign the metrics belong to. Joins to `campaigns.id`.",
        },
    },
    "list_users": {
        "description": "Membership of Iterable lists: one row per user in each list.",
        "docs_url": "https://api.iterable.com/api/docs#lists_getLists_0",
        "columns": {
            "listId": "Identifier of the list. Joins to `lists.id`.",
            "email": "Email of the list member, or the userId for a user without an email.",
        },
    },
    "users": {
        "description": "User profiles in the Iterable project, from the Export API.",
        "docs_url": "https://api.iterable.com/api/docs#export_exportDataJson",
        "columns": {
            "email": "The user's email address.",
            "userId": "The user's userId, when set.",
            "profileUpdatedAt": "Time at which the user's profile was last updated.",
            "signupDate": "Time at which the user signed up.",
        },
    },
    "email_send": {
        "description": "One row per email Iterable sent, from the Export API.",
        "docs_url": "https://api.iterable.com/api/docs#export_exportDataJson",
        "columns": {
            "createdAt": "Time at which the email was sent.",
            "email": "Email address of the recipient.",
            "campaignId": "Identifier of the campaign that sent the email. Joins to `campaigns.id`.",
            "templateId": "Identifier of the template used. Joins to `templates.templateId`.",
            "messageId": "Identifier of the sent message, shared by its open, click and bounce events.",
        },
    },
}
