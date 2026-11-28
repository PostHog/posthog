from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "websites": {
        "description": "Websites available to the account, including team websites.",
        "docs_url": "https://docs.umami.is/docs/api-reference/list-websites",
        "columns": {
            "id": "Unique website identifier.",
            "name": "Website name.",
            "domain": "Website domain.",
            "teamId": "Team that owns the website.",
            "createdAt": "Time when the website was created.",
        },
    },
    "sessions": {
        "description": "Visitor sessions and activity counts across the available website history.",
        "docs_url": "https://docs.umami.is/docs/api-reference/get-website-sessions",
        "columns": {
            "id": "Unique session identifier.",
            "websiteId": "Website associated with the session.",
            "browser": "Browser used by the visitor.",
            "os": "Operating system used by the visitor.",
            "device": "Device category used by the visitor.",
            "country": "Country code of the visitor.",
            "createdAt": "Time when the session was created.",
            "views": "Pageview count within the requested date range.",
            "events": "Custom event count within the requested date range.",
        },
    },
    "events": {
        "description": "Individual pageviews and custom events recorded for each website.",
        "docs_url": "https://docs.umami.is/docs/api-reference/get-website-events",
        "columns": {
            "id": "Unique event identifier.",
            "websiteId": "Website associated with the event.",
            "sessionId": "Session associated with the event.",
            "createdAt": "Time when the event was recorded.",
            "eventType": "Event type: 1 for a pageview or 2 for a custom event.",
            "eventName": "Custom event name.",
            "urlPath": "Path of the page URL.",
            "referrerDomain": "Domain of the referring URL.",
        },
    },
    "event_properties": {
        "description": "Custom properties grouped by event.",
        "docs_url": "https://docs.umami.is/docs/api-reference/get-event-data",
        "columns": {
            "websiteId": "Website associated with the event.",
            "eventId": "Identifier of the event in the events table.",
            "createdAt": "Time when Umami recorded the event properties.",
            "eventProperties": "Property keys, types, and values recorded with the event.",
        },
    },
    "goals": {
        "description": "Saved conversion goals for each website.",
        "docs_url": "https://docs.umami.is/docs/api-reference/get-website-goals",
        "columns": {
            "id": "Goal identifier.",
            "websiteId": "Website associated with the goal.",
            "name": "Goal name.",
            "parameters": "Settings that define the goal.",
        },
    },
    "session_properties": {
        "description": "Custom properties grouped by session.",
        "docs_url": "https://docs.umami.is/docs/api-reference/get-website-session-properties",
        "columns": {
            "websiteId": "Website associated with the session.",
            "sessionId": "Identifier of the session in the sessions table.",
            "createdAt": "Time when the session began.",
            "sessionProperties": "Property keys, types, and values recorded during the session.",
        },
    },
    "funnels": {
        "description": "Saved funnels for each website.",
        "docs_url": "https://docs.umami.is/docs/api-reference/get-website-funnels",
        "columns": {
            "id": "Funnel identifier.",
            "websiteId": "Website associated with the funnel.",
            "name": "Funnel name.",
            "parameters": "Settings that define the funnel steps and time window.",
        },
    },
}
