from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.proofpoint_tap.settings import API_DOCS_URL

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
}
