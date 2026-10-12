from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the Eventzilla API v2 reference (https://developer.eventzilla.net/docs/). Partial
# coverage is fine — any endpoint/column not listed here falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "Events created in your Eventzilla account, with their scheduling, capacity, and status.",
        "docs_url": "https://developer.eventzilla.net/docs/",
        "columns": {
            "id": "Unique identifier for the event.",
            "title": "Event title.",
            "description": "Event description (HTML).",
            "currency": "Currency the event's tickets are priced in.",
            "start_date": "Date the event starts.",
            "end_date": "Date the event ends.",
            "start_time": "Time the event starts.",
            "end_time": "Time the event ends.",
            "date_id": "Identifier of the event's date (events can have multiple dates).",
            "time_zone": "Time zone the event is scheduled in.",
            "tickets_sold": "Number of tickets sold so far.",
            "total_tickets": "Total number of tickets available.",
            "status": "Event status (e.g. Live, Draft, Unpublished, Completed).",
        },
    },
    "categories": {
        "description": "The reference list of event categories available in Eventzilla.",
        "docs_url": "https://developer.eventzilla.net/docs/",
        "columns": {
            "category": "Name of the category.",
        },
    },
    "users": {
        "description": "Users (organizers) in your Eventzilla account.",
        "docs_url": "https://developer.eventzilla.net/docs/",
        "columns": {
            "id": "Unique identifier for the user.",
            "last_seen": "Timestamp the user was last seen.",
        },
    },
    "attendees": {
        "description": "Attendees registered for each event. Fetched per event.",
        "docs_url": "https://developer.eventzilla.net/docs/",
        "columns": {
            "id": "Unique identifier for the attendee.",
            "event_id": "Identifier of the event this attendee belongs to (added by PostHog during fan-out).",
            "bar_code": "Barcode encoded on the attendee's ticket.",
            "transaction_ref": "Order reference of the transaction that created this attendee.",
            "transaction_date": "Timestamp the purchasing transaction was made.",
            "event_date": "Date of the event the attendee registered for.",
        },
    },
    "transactions": {
        "description": "Ticket purchase transactions for each event. Fetched per event.",
        "docs_url": "https://developer.eventzilla.net/docs/",
        "columns": {
            "checkout_id": "Unique identifier for the transaction.",
            "event_id": "Identifier of the event this transaction belongs to.",
            "transaction_ref": "Order reference for the transaction.",
            "transaction_date": "Timestamp the transaction was made.",
            "transaction_amount": "Total amount of the transaction.",
            "tickets_in_transaction": "Number of tickets (attendees) in the transaction.",
            "transaction_status": "Status of the transaction (e.g. Confirmed, Pending, Cancelled, Incomplete).",
            "event_date": "Date of the event the transaction is for.",
            "user_id": "Identifier of the buyer.",
            "email": "Buyer's email address.",
            "buyer_first_name": "Buyer's first name.",
            "buyer_last_name": "Buyer's last name.",
            "promo_code": "Promo code applied to the transaction, if any.",
            "payment_type": "Payment method used.",
        },
    },
    "tickets": {
        "description": "Ticket types configured for each event. Fetched per event.",
        "docs_url": "https://developer.eventzilla.net/docs/",
        "columns": {
            "id": "Unique identifier for the ticket type.",
            "event_id": "Identifier of the event this ticket type belongs to (added by PostHog during fan-out).",
            "sales_start_date": "Date ticket sales start.",
            "sales_end_date": "Date ticket sales end.",
        },
    },
}
