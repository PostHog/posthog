from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Humanitix Public API docs (https://api.humanitix.com/v1/documentation).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "A Humanitix event — a ticketed event with its dates, location, capacity, and publishing state.",
        "docs_url": "https://humanitix.stoplight.io/docs/humanitix-public-api/476881e4b5d55-get-events",
        "columns": {
            "_id": "The unique ID of the event.",
            "userId": "The ID of the user that owns the event.",
            "name": "The name of the event.",
            "description": "The event description.",
            "slug": "The URL slug of the event.",
            "dates": "The event's date ranges, each with a start and end time.",
            "startDate": "The start date and time of the event.",
            "endDate": "The end date and time of the event.",
            "timezone": "The IANA timezone the event dates are expressed in.",
            "location": "The event's location as an ISO 3166-1 alpha-2 country code.",
            "eventLocation": "The venue details for the event (address, coordinates, and venue type).",
            "totalCapacity": "The maximum number of attendees the event can hold.",
            "currency": "The currency code used for ticket pricing.",
            "published": "Whether the event is published.",
            "public": "Whether the event is publicly visible.",
            "classification": "The event's type and category classification.",
            "ticketTypes": "The ticket types configured for the event.",
            "createdAt": "The date and time the event was created.",
            "updatedAt": "The date and time the event was last modified.",
        },
    },
    "tags": {
        "description": "A Humanitix tag — a label used to group and organise events in an account.",
        "docs_url": "https://api.humanitix.com/v1/documentation",
        "columns": {
            "_id": "The unique ID of the tag.",
            "name": "The display name of the tag.",
            "userId": "The ID of the user that owns the tag.",
            "location": "The tag's location as an ISO 3166-1 alpha-2 country code.",
            "createdAt": "The date and time the tag was created.",
            "updatedAt": "The date and time the tag was last modified.",
        },
    },
}
