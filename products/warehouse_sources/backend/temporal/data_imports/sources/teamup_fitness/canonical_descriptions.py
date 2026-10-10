from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "customers": {
        "description": "Customers of the TeamUp business, including their contact details and status.",
        "docs_url": "https://docs.goteamup.com/api-reference/endpoints/customers-list",
        "columns": {
            "id": "Unique customer identifier.",
            "created_at": "Date and time when the customer was created.",
            "email": "Customer email address.",
            "first_name": "Customer first name.",
            "last_name": "Customer last name.",
            "status": "Customer status in the business.",
            "provider": "Identifier of the TeamUp business.",
        },
    },
    "customer_memberships": {
        "description": "Memberships held by customers, including their dates, status, and billed price.",
        "docs_url": "https://docs.goteamup.com/api-reference/endpoints/customer-memberships-list",
        "columns": {
            "id": "Unique identifier for the customer's membership.",
            "customer": "Identifier of the customer who owns the membership.",
            "membership": "Identifier of the membership product.",
            "start_date": "Date when the customer's membership starts.",
            "expiration_date": "Date when the customer's membership expires, if set.",
            "status": "Current status of the customer's membership.",
            "billed_price": "Price billed for the customer's membership.",
        },
    },
    "memberships": {
        "description": "Membership products, including recurring memberships, prepaid memberships, and packs.",
        "docs_url": "https://docs.goteamup.com/api-reference/endpoints/memberships-list",
        "columns": {
            "id": "Unique membership product identifier.",
            "name": "Membership name.",
            "type": "Membership type.",
            "price": "Membership price.",
            "active_member_count": "Number of active members.",
            "for_sale": "Whether the membership is available for sale.",
        },
    },
    "events": {
        "description": "Scheduled classes and appointments, including their times, locations, and attendance counts.",
        "docs_url": "https://docs.goteamup.com/api-reference/endpoints/events-list",
        "columns": {
            "id": "Unique event identifier.",
            "name": "Event name.",
            "starts_at": "Date and time when the event starts.",
            "ends_at": "Date and time when the event ends.",
            "status": "Whether the event is active or canceled.",
            "attending_count": "Number of customers registered for the event.",
            "waiting_count": "Number of customers on the waitlist.",
            "venue": "Identifier of the event venue.",
        },
    },
    "attendances": {
        "description": "Customer registrations and attendance status for events.",
        "docs_url": "https://docs.goteamup.com/api-reference/endpoints/attendances-list",
        "columns": {
            "id": "Unique attendance identifier.",
            "customer": "Identifier of the customer.",
            "event": "Identifier of the event.",
            "status": "Registration or attendance status, such as registered, attended, or no_show.",
            "customer_membership": "Customer membership used for the registration.",
            "booking_source": "Application where the original booking was made.",
        },
    },
    "invoices": {
        "description": "Invoices with payment status, payer, due date, and total amount due.",
        "docs_url": "https://docs.goteamup.com/api-reference/endpoints/invoices-list",
        "columns": {
            "id": "Unique invoice identifier.",
            "created_at": "Date and time when the invoice was created.",
            "due_date": "Date when the invoice is due.",
            "status": "Current invoice payment status.",
            "total_amount_due": "Total amount due on the invoice.",
            "is_credit_note": "Whether the invoice is a credit note.",
        },
    },
    "venues": {
        "description": "Physical and online venues where the business holds events.",
        "docs_url": "https://docs.goteamup.com/api-reference/endpoints/venues-list",
        "columns": {
            "id": "Unique venue identifier.",
            "name": "Venue name.",
            "timezone": "Venue timezone.",
            "archived": "Whether the venue is archived.",
            "is_online": "Whether the venue is online.",
        },
    },
    "instructors": {
        "description": "Instructors who deliver classes and appointments for the business.",
        "docs_url": "https://docs.goteamup.com/api-reference/endpoints/instructors-list",
        "columns": {
            "id": "Unique instructor identifier.",
            "name": "Instructor name.",
            "description": "Instructor description.",
            "staff": "Identifier of the associated staff member.",
        },
    },
}
