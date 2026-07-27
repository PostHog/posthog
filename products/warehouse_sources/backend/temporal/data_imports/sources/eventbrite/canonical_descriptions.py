"""Canonical, documentation-sourced descriptions for Eventbrite endpoints and columns.

Sourced from the official Eventbrite API reference (https://www.eventbrite.com/platform/api).
Keyed by the endpoint names in `settings.py` `EVENTBRITE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Eventbrite table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "organizations": {
        "description": "An Eventbrite organization (account) that owns events, venues, and orders.",
        "docs_url": "https://www.eventbrite.com/platform/api#/reference/organization",
        "columns": {
            "id": "Unique identifier for the organization.",
            "name": "The organization's name.",
            "vertical": "The organization's business vertical.",
            "image_id": "Identifier of the organization's logo image.",
            "_type": "String naming the Eventbrite object type.",
            "parent_id": "ID of the parent organization, if this is a sub-organization.",
        },
    },
    "categories": {
        "description": "A top-level event category in Eventbrite's taxonomy (e.g. Music, Business).",
        "docs_url": "https://www.eventbrite.com/platform/api#/reference/category",
        "columns": {
            "id": "Unique identifier for the category.",
            "name": "Localized display name of the category.",
            "name_localized": "Localized name of the category.",
            "short_name": "Short display name of the category.",
        },
    },
    "formats": {
        "description": "An event format describing the style of an event (e.g. Conference, Seminar).",
        "docs_url": "https://www.eventbrite.com/platform/api#/reference/format",
        "columns": {
            "id": "Unique identifier for the format.",
            "name": "Display name of the format.",
            "short_name": "Short display name of the format.",
        },
    },
    "events": {
        "description": "An event published by an organization, with its schedule, status, and venue.",
        "docs_url": "https://www.eventbrite.com/platform/api#/reference/event",
        "columns": {
            "id": "Unique identifier for the event.",
            "name": "The event's title (a multipart text object).",
            "description": "The event's description (a multipart text object).",
            "url": "Public Eventbrite URL of the event.",
            "start": "Event start time, with timezone and UTC representations.",
            "end": "Event end time, with timezone and UTC representations.",
            "created": "Time at which the event was created.",
            "changed": "Time at which the event was last changed.",
            "status": "Event status (e.g. draft, live, started, ended, completed, canceled).",
            "currency": "ISO 4217 currency code used for the event's tickets.",
            "online_event": "Whether the event is held online.",
            "organization_id": "ID of the organization that owns the event.",
            "organizer_id": "ID of the organizer presenting the event.",
            "venue_id": "ID of the venue where the event is held, if any.",
            "category_id": "ID of the event's category.",
            "format_id": "ID of the event's format.",
            "capacity": "Maximum number of attendees for the event.",
        },
    },
    "venues": {
        "description": "A physical location where an organization's events are held.",
        "docs_url": "https://www.eventbrite.com/platform/api#/reference/venue",
        "columns": {
            "id": "Unique identifier for the venue.",
            "name": "The venue's name.",
            "address": "Structured postal address of the venue.",
            "latitude": "Latitude of the venue's location.",
            "longitude": "Longitude of the venue's location.",
            "capacity": "Maximum capacity of the venue.",
        },
    },
    "orders": {
        "description": "An order placed by an attendee to purchase tickets to an event.",
        "docs_url": "https://www.eventbrite.com/platform/api#/reference/order",
        "columns": {
            "id": "Unique identifier for the order.",
            "event_id": "ID of the event the order is for.",
            "created": "Time at which the order was created.",
            "changed": "Time at which the order was last changed.",
            "name": "Full name of the buyer.",
            "first_name": "First name of the buyer.",
            "last_name": "Last name of the buyer.",
            "email": "Email address of the buyer.",
            "status": "Order status (e.g. placed, refunded, deleted).",
            "costs": "Breakdown of the order's costs (base price, fees, tax, total).",
            "time_remaining": "Seconds remaining to complete the order, if pending.",
        },
    },
    "attendees": {
        "description": "An attendee on an order — one ticket holder for an event.",
        "docs_url": "https://www.eventbrite.com/platform/api#/reference/attendee",
        "columns": {
            "id": "Unique identifier for the attendee.",
            "event_id": "ID of the event the attendee is registered for.",
            "order_id": "ID of the order the attendee belongs to.",
            "ticket_class_id": "ID of the ticket class the attendee holds.",
            "created": "Time at which the attendee record was created.",
            "changed": "Time at which the attendee record was last changed.",
            "status": "Attendee status (e.g. Attending, Not Attending, Checked In).",
            "checked_in": "Whether the attendee has been checked in.",
            "cancelled": "Whether the attendee has been cancelled.",
            "refunded": "Whether the attendee's ticket has been refunded.",
            "profile": "Attendee profile details (name, email, and custom answers).",
            "costs": "Cost breakdown for the attendee's ticket.",
            "quantity": "Number of tickets in this attendee record.",
        },
    },
    "ticket_classes": {
        "description": "A type of ticket sold for an event, with its price and availability.",
        "docs_url": "https://www.eventbrite.com/platform/api#/reference/ticket-class",
        "columns": {
            "id": "Unique identifier for the ticket class.",
            "event_id": "ID of the event this ticket class belongs to.",
            "name": "The ticket class's name.",
            "description": "Description of the ticket class.",
            "cost": "Display price of the ticket, including currency and value.",
            "actual_cost": "Actual price charged for the ticket, as a currency object.",
            "fee": "Eventbrite fee applied to the ticket.",
            "on_sale_status": "Current sale status of the ticket class (e.g. AVAILABLE, SOLD_OUT, UNAVAILABLE).",
            "free": "Whether the ticket is free.",
            "quantity_total": "Total number of tickets available in this class.",
            "quantity_sold": "Number of tickets sold from this class.",
            "sales_start": "Time at which sales for this ticket class start.",
            "sales_end": "Time at which sales for this ticket class end.",
            "hidden": "Whether the ticket class is hidden from buyers.",
        },
    },
}
