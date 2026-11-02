from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "Saved event definitions in the Smartlook project.",
        "docs_url": "https://integrations.smartlook.com/reference/geteventslist",
        "columns": {
            "id": "The event definition identifier.",
            "name": "The event definition name.",
            "categoryId": "The event category identifier.",
            "categoryName": "The event category name.",
        },
    },
    "funnels": {
        "description": "Saved funnels and their ordered event definitions.",
        "docs_url": "https://integrations.smartlook.com/reference/getfunnelslist",
        "columns": {
            "id": "The funnel identifier.",
            "name": "The funnel name.",
            "events": "The event definitions that form the funnel.",
        },
    },
    "sessions": {
        "description": "Session recording metadata and links to the Smartlook player.",
        "docs_url": "https://integrations.smartlook.com/reference/searchsessions",
        "columns": {
            "id": "The session identifier.",
            "visitorId": "The visitor identifier for the session.",
            "startedAt": "The time when the session started.",
            "endedAt": "The time when the session ended.",
            "duration": "The session duration.",
            "dashboardURL": "The link to the session in Smartlook.",
        },
    },
    "visitor_events": {
        "description": "Recorded interactions for each visitor, including custom events, clicks, and errors.",
        "docs_url": "https://integrations.smartlook.com/reference/getvisitorevents",
        "columns": {
            "id": "The recorded event identifier.",
            "visitor_id": "The visitor identifier from the parent search result.",
            "visitorId": "The visitor identifier returned with the event.",
            "sessionId": "The session identifier for the event.",
            "startedAt": "The time when the event started.",
            "type": "The interaction type.",
            "eventName": "The event name.",
        },
    },
    "visitors": {
        "description": "Visitors with identification properties and the times of their first and last visits.",
        "docs_url": "https://integrations.smartlook.com/reference/searchvisitors",
        "columns": {
            "id": "The visitor identifier.",
            "firstSeen": "The time when Smartlook first saw the visitor.",
            "lastSeen": "The time when Smartlook last saw the visitor.",
            "identification": "The user identifier and custom identification properties.",
        },
    },
}
