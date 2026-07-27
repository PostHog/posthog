from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions are taken from the official lemlist API reference
# (https://developer.lemlist.com/api-reference). Keys match the endpoint/schema names returned by
# `get_schemas` (see settings.LEMLIST_ENDPOINTS). Columns not listed here fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "Cold-outreach campaigns in your lemlist team, each a multichannel email/LinkedIn sequence sent to leads.",
        "docs_url": "https://developer.lemlist.com/api-reference/endpoints/campaigns/get-many-campaigns",
        "columns": {
            "_id": "Unique campaign identifier (e.g. cam_xxx).",
            "name": "Campaign name.",
            "labels": "Labels applied to the campaign.",
            "status": "Campaign status (running, draft, archived, ended, paused, errors).",
            "createdAt": "When the campaign was created.",
            "createdBy": "User ID of the campaign creator.",
            "teamId": "ID of the team that owns the campaign.",
            "hasError": "Whether the campaign currently has a configuration error.",
            "errors": "List of campaign error messages.",
        },
    },
    "activities": {
        "description": "Per-lead activity events in your campaigns (emails opened, clicked, replied, LinkedIn actions, etc.). Append-only event log filterable by createdAt.",
        "docs_url": "https://developer.lemlist.com/api-reference/endpoints/activities/get-many-activities",
        "columns": {
            "_id": "Unique activity identifier.",
            "type": "Activity type (e.g. emailsOpened, emailsClicked, emailsReplied, linkedinReplied).",
            "leadId": "ID of the lead the activity relates to.",
            "campaignId": "ID of the campaign the activity belongs to.",
            "sequenceId": "ID of the sequence the activity belongs to.",
            "stepId": "ID of the sequence step that produced the activity.",
            "createdAt": "When the activity occurred.",
        },
    },
    "team": {
        "description": "Your lemlist team account, including configured webhooks and invited users.",
        "docs_url": "https://developer.lemlist.com/api-reference/endpoints/team/get-team",
        "columns": {
            "_id": "Unique team identifier.",
            "name": "Team name.",
            "userIds": "User IDs that belong to the team.",
            "createdBy": "User ID that created the team.",
            "createdAt": "When the team was created.",
        },
    },
    "team_senders": {
        "description": "Sender accounts configured for the team and the campaigns each sender is attached to.",
        "docs_url": "https://developer.lemlist.com/api-reference/endpoints/team/get-team-senders",
        "columns": {
            "userId": "User ID of the sender.",
            "campaigns": "Campaigns the sender is attached to, with id, name, status and sending channels.",
        },
    },
    "unsubscribes": {
        "description": "Contacts that have unsubscribed from your team's outreach.",
        "docs_url": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/get-many-unsubscribes",
        "columns": {
            "_id": "Unique unsubscribe identifier.",
            "email": "Email address that unsubscribed.",
            "createdAt": "When the unsubscribe was recorded.",
            "campaignId": "Campaign the contact unsubscribed from, if scoped to a campaign.",
            "scope": "Scope of the unsubscribe (campaign, team or global).",
        },
    },
}
