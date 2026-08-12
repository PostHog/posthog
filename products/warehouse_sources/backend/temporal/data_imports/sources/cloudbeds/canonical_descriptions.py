from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Cloudbeds PMS API v1.2 docs (https://developers.cloudbeds.com).
# Partial coverage is fine - uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "hotels": {
        "description": "A property (hotel, hostel, or vacation rental) managed by the Cloudbeds account.",
        "docs_url": "https://developers.cloudbeds.com",
        "columns": {
            "propertyID": "The unique ID of the property.",
            "propertyName": "The name of the property.",
            "propertyType": "The type of property (e.g. hotel, hostel, vacation rental).",
            "propertyCurrency": "The currency the property operates in.",
            "propertyPhone": "The property's contact phone number.",
            "propertyEmail": "The property's contact email address.",
        },
    },
    "reservations": {
        "description": "A booking at a property, covering one or more rooms and guests.",
        "docs_url": "https://developers.cloudbeds.com",
        "columns": {
            "reservationID": "The unique ID of the reservation.",
            "propertyID": "The ID of the property the reservation belongs to.",
            "guestID": "The ID of the primary guest on the reservation.",
            "guestName": "The name of the primary guest on the reservation.",
            "status": "The reservation status (e.g. confirmed, checked_in, checked_out, canceled, no_show).",
            "startDate": "The check-in date of the reservation.",
            "endDate": "The check-out date of the reservation.",
            "dateCreated": "When the reservation was created.",
            "dateModified": "When the reservation was last modified.",
            "sourceName": "The booking source or channel the reservation came from.",
            "balance": "The outstanding balance on the reservation.",
        },
    },
    "guests": {
        "description": "A guest profile stored at the property, linked to one or more reservations.",
        "docs_url": "https://developers.cloudbeds.com",
        "columns": {
            "guestID": "The unique ID of the guest.",
            "propertyID": "The ID of the property the guest profile belongs to.",
            "guestFirstName": "The guest's first name.",
            "guestLastName": "The guest's last name.",
            "guestEmail": "The guest's email address.",
            "guestPhone": "The guest's phone number.",
            "guestCountry": "The guest's country.",
            "reservationID": "The ID of the reservation the guest is associated with.",
        },
    },
    "rooms": {
        "description": "A physical room (or unit) at a property, listed per property by the rooms endpoint.",
        "docs_url": "https://developers.cloudbeds.com",
        "columns": {
            "roomID": "The unique ID of the room.",
            "propertyID": "The ID of the property the room belongs to.",
            "roomName": "The name or number of the room.",
            "roomTypeID": "The ID of the room type the room belongs to.",
            "roomTypeName": "The name of the room type the room belongs to.",
            "roomBlocked": "Whether the room is currently blocked from sale.",
        },
    },
    "room_types": {
        "description": "A room category at a property (e.g. double, dorm bed) with its occupancy and inventory settings.",
        "docs_url": "https://developers.cloudbeds.com",
        "columns": {
            "roomTypeID": "The unique ID of the room type.",
            "propertyID": "The ID of the property the room type belongs to.",
            "roomTypeName": "The name of the room type.",
            "roomTypeNameShort": "The short code of the room type.",
            "maxGuests": "The maximum number of guests the room type accommodates.",
            "isPrivate": "Whether the room type is a private room (as opposed to a shared/dorm room).",
            "roomsAvailable": "The number of rooms of this type available for sale.",
        },
    },
    "transactions": {
        "description": "A financial transaction (charge, payment, tax, or adjustment) posted at the property.",
        "docs_url": "https://developers.cloudbeds.com",
        "columns": {
            "transactionID": "The unique ID of the transaction.",
            "propertyID": "The ID of the property the transaction belongs to.",
            "reservationID": "The ID of the reservation the transaction is attached to, if any.",
            "guestID": "The ID of the guest the transaction is attached to, if any.",
            "amount": "The amount of the transaction.",
            "currency": "The currency of the transaction.",
            "description": "The description of the transaction.",
            "transactionDateTime": "When the transaction was posted.",
        },
    },
}
