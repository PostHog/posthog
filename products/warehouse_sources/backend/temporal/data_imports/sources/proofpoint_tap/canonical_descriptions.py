from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.proofpoint_tap.settings import API_DOCS_URL

DOCS_ROOT = "https://help.proofpoint.com/Threat_Insight_Dashboard/API_Documentation"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "clicks_blocked": {
        "description": "Blocked clicks on malicious URLs.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Unique click identifier.",
            "clickTime": "Time of the click.",
            "threatID": "Threat identifier.",
            "query_end_time": "End of the query interval that returned this event, added by PostHog.",
        },
    },
    "clicks_permitted": {
        "description": "Permitted clicks on malicious URLs.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Unique click identifier.",
            "clickTime": "Time of the click.",
            "threatTime": "Time when Proofpoint identified the threat.",
            "query_end_time": "End of the query interval that returned this event, added by PostHog.",
        },
    },
    "messages_blocked": {
        "description": "Quarantined messages with detected threats.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "GUID": "Unique message identifier in Proofpoint Protection Server.",
            "messageTime": "Time of delivery or quarantine.",
            "threatsInfoMap": "Threat details for this message.",
            "query_end_time": "End of the query interval that returned this event, added by PostHog.",
        },
    },
    "messages_delivered": {
        "description": "Delivered messages with detected threats.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "GUID": "Unique message identifier in Proofpoint Protection Server.",
            "messageTime": "Time of delivery or quarantine.",
            "threatsInfoMap": "Threat details for this message.",
            "query_end_time": "End of the query interval that returned this event, added by PostHog.",
        },
    },
    "threats": {
        "description": "Threat summaries for the threats that SIEM events reference.",
        "docs_url": f"{DOCS_ROOT}/Threat_API",
        "columns": {
            "id": "Unique threat identifier.",
            "identifiedAt": "Time when Proofpoint identified the threat.",
            "name": "Threat name, such as a URL or an attachment hash.",
            "type": "Threat type, such as url or attachment.",
            "category": "Threat category, such as malware or phish.",
            "status": "Threat status, such as active or cleared.",
            "severity": "Threat severity score from 0 to 1000.",
            "attackSpread": "Number of other customers that received this threat.",
            "families": "Threat families of the threat.",
            "query_end_time": "End of the SIEM query interval that first returned this threat in a sync, added by PostHog.",
        },
    },
    "campaigns": {
        "description": "Campaigns updated in the queried interval, with their threats, actors and malware.",
        "docs_url": f"{DOCS_ROOT}/Campaign_API",
        "columns": {
            "id": "Unique campaign identifier.",
            "name": "Campaign name.",
            "description": "Campaign description.",
            "startDate": "Start date of the campaign.",
            "lastUpdatedAt": "Time of the last update to the campaign.",
            "campaignMembers": "Threats that belong to the campaign.",
            "actors": "Threat actors associated with the campaign.",
            "malware": "Malware families associated with the campaign.",
            "techniques": "Attack techniques associated with the campaign.",
            "query_end_time": "End of the campaign ID query interval that returned this campaign, added by PostHog.",
        },
    },
    "very_attacked_people": {
        "description": "Very Attacked People in your organization over the last 90 days, ranked by attack index.",
        "docs_url": f"{DOCS_ROOT}/People_API",
        "columns": {
            "guid": "Unique identifier of the user, added by PostHog from the identity.",
            "identity": "User identity: emails, name, department, location, title and VIP status.",
            "threatStatistics": "Attack index of the user and the score of each threat family.",
            "interval": "Time interval of the data, in ISO 8601 format.",
        },
    },
    "top_clickers": {
        "description": "Users who clicked the most malicious URLs over the last 90 days.",
        "docs_url": f"{DOCS_ROOT}/People_API",
        "columns": {
            "guid": "Unique identifier of the user, added by PostHog from the identity.",
            "identity": "User identity: emails, name, department, location, title and VIP status.",
            "clickStatistics": "Click count of the user and the clicks for each threat family.",
            "interval": "Time interval of the data, in ISO 8601 format.",
        },
    },
}
