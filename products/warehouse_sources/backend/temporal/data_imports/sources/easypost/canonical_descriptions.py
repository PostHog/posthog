from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the official EasyPost API docs (https://docs.easypost.com). Partial coverage is fine —
# any uncovered endpoint/column falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "shipments": {
        "description": "A request to ship a parcel between two addresses, including rates, the purchased label (postage_label), and tracking.",
        "docs_url": "https://docs.easypost.com/docs/shipments",
        "columns": {
            "id": 'Unique identifier for the shipment, begins with "shp_".',
            "mode": 'Whether the shipment was created in "test" or "production" mode.',
            "status": "Current status of the shipment (e.g. unknown, pre_transit, in_transit, delivered).",
            "tracking_code": "Tracking code assigned by the carrier once postage is purchased.",
            "to_address": "The destination address object.",
            "from_address": "The origin address object.",
            "parcel": "The parcel (dimensions and weight) being shipped.",
            "rates": "Available carrier rates for this shipment.",
            "selected_rate": "The rate that was purchased for this shipment.",
            "postage_label": "The purchased shipping label, including its image URL.",
            "created_at": "When the shipment was created.",
            "updated_at": "When the shipment was last updated.",
        },
    },
    "trackers": {
        "description": "Tracks the progress of a parcel through a carrier's network, with status and per-scan tracking details.",
        "docs_url": "https://docs.easypost.com/docs/trackers",
        "columns": {
            "id": 'Unique identifier for the tracker, begins with "trk_".',
            "mode": 'Whether the tracker was created in "test" or "production" mode.',
            "tracking_code": "The tracking code being tracked.",
            "status": "Current delivery status (e.g. pre_transit, in_transit, out_for_delivery, delivered, failure).",
            "carrier": "The carrier handling the parcel.",
            "tracking_details": "Ordered list of scan events recorded for the parcel.",
            "est_delivery_date": "Estimated delivery date reported by the carrier.",
            "created_at": "When the tracker was created.",
            "updated_at": "When the tracker was last updated.",
        },
    },
    "events": {
        "description": "An immutable record of a change to an EasyPost object (e.g. tracker.updated), the same payload delivered to webhooks.",
        "docs_url": "https://docs.easypost.com/docs/events",
        "columns": {
            "id": 'Unique identifier for the event, begins with "evt_".',
            "object": 'The string "Event".',
            "description": "Result type and event name (e.g. tracker.created).",
            "mode": 'Whether the event was created in "test" or "production" mode.',
            "status": "Delivery status of the associated webhook, if any.",
            "created_at": "When the event was created.",
            "updated_at": "When the event was last updated.",
        },
    },
    "batches": {
        "description": "A group of shipments processed together, used for bulk label purchase and scan form generation.",
        "docs_url": "https://docs.easypost.com/docs/batches",
        "columns": {
            "id": 'Unique identifier for the batch, begins with "batch_".',
            "state": "Current processing state of the batch (e.g. creating, created, purchased).",
            "num_shipments": "Number of shipments in the batch.",
            "created_at": "When the batch was created.",
            "updated_at": "When the batch was last updated.",
        },
    },
    "addresses": {
        "description": "A physical address, optionally verified, used as the origin or destination of shipments.",
        "docs_url": "https://docs.easypost.com/docs/addresses",
        "columns": {
            "id": 'Unique identifier for the address, begins with "adr_".',
            "street1": "First line of the street address.",
            "street2": "Second line of the street address.",
            "city": "City.",
            "state": "State or province.",
            "zip": "Postal code.",
            "country": "ISO 3166 country code.",
            "created_at": "When the address was created.",
            "updated_at": "When the address was last updated.",
        },
    },
    "insurances": {
        "description": "Insurance purchased against loss or damage for a shipment.",
        "docs_url": "https://docs.easypost.com/docs/insurance",
        "columns": {
            "id": 'Unique identifier for the insurance, begins with "ins_".',
            "amount": "Insured value of the parcel.",
            "status": "Current status of the insurance claim/coverage.",
            "tracking_code": "Tracking code of the insured shipment.",
            "created_at": "When the insurance was created.",
            "updated_at": "When the insurance was last updated.",
        },
    },
    "refunds": {
        "description": "A request to refund the postage cost of a purchased label.",
        "docs_url": "https://docs.easypost.com/docs/refunds",
        "columns": {
            "id": 'Unique identifier for the refund, begins with "rfnd_".',
            "status": "Current status of the refund (e.g. submitted, refunded, rejected).",
            "tracking_code": "Tracking code of the shipment being refunded.",
            "carrier": "Carrier the refund was requested from.",
            "created_at": "When the refund was created.",
            "updated_at": "When the refund was last updated.",
        },
    },
    "scan_forms": {
        "description": "A manifest (SCAN form) covering a set of shipments for a single carrier pickup.",
        "docs_url": "https://docs.easypost.com/docs/scan-form",
        "columns": {
            "id": 'Unique identifier for the scan form, begins with "sf_".',
            "status": "Current status of the scan form.",
            "tracking_codes": "Tracking codes of the shipments included on the scan form.",
            "created_at": "When the scan form was created.",
            "updated_at": "When the scan form was last updated.",
        },
    },
    "pickups": {
        "description": "A scheduled carrier pickup for one or more shipments.",
        "docs_url": "https://docs.easypost.com/docs/pickups",
        "columns": {
            "id": 'Unique identifier for the pickup, begins with "pickup_".',
            "status": "Current status of the pickup (e.g. unknown, scheduled, canceled).",
            "reference": "Optional user-supplied reference for the pickup.",
            "min_datetime": "Earliest time the parcel is available for pickup.",
            "max_datetime": "Latest time the parcel is available for pickup.",
            "created_at": "When the pickup was created.",
            "updated_at": "When the pickup was last updated.",
        },
    },
}
