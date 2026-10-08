from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ticketmaster.settings import API_DOCS_URL

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "Public events that match the configured search keyword.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Unique event identifier in the Discovery API.",
            "name": "Event name.",
            "url": "URL of the event page.",
            "dates": "Event dates, times, timezone, and status.",
            "sales": "Public sale and presale dates.",
            "classifications": "Categories that describe the event.",
            "priceRanges": "Ticket price ranges and currencies.",
            "_embedded": "Venues and attractions linked to the event.",
        },
    },
    "attractions": {
        "description": "Artists, teams, and other attractions that match the configured search keyword.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Unique attraction identifier in the Discovery API.",
            "name": "Attraction name.",
            "url": "URL of the attraction page.",
            "classifications": "Categories that describe the attraction.",
            "upcomingEvents": "Number of upcoming events.",
        },
    },
    "venues": {
        "description": "Event venues that match the configured search keyword.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Unique venue identifier in the Discovery API.",
            "name": "Venue name.",
            "address": "Venue street address.",
            "city": "Venue city.",
            "country": "Venue country and country code.",
            "location": "Venue latitude and longitude.",
            "timezone": "Venue timezone.",
        },
    },
}
