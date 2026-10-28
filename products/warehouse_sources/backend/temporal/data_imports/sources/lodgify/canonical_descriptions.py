from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "properties": {
        "description": "Rental properties with location, prices, room types, and account status.",
        "docs_url": "https://docs.lodgify.com/reference/getallpropertiesasync",
        "columns": {
            "id": "Unique property identifier.",
            "name": "Property name.",
            "created_at": "Time when the property was created.",
            "updated_at": "Time of the latest property update.",
            "currency_code": "Currency for the property prices.",
            "is_active": "Whether the property is linked to a valid website.",
        },
    },
    "bookings": {
        "description": "Bookings across all stay dates, including trash, transaction details, and quote details.",
        "docs_url": "https://docs.lodgify.com/reference/getallasync",
        "columns": {
            "id": "Unique booking identifier.",
            "property_id": "Identifier of the booked property.",
            "arrival": "Guest arrival date.",
            "departure": "Guest departure date.",
            "created_at": "Time when the booking was created.",
            "updated_at": "Time of the latest booking update.",
            "is_deleted": "Whether the owner moved the booking to trash.",
            "currency_code": "Currency for the booking amounts.",
        },
    },
    "rooms": {
        "description": "Room types for each property, with capacity, amenities, and prices.",
        "docs_url": "https://docs.lodgify.com/reference/propertiesapi_v_getallrooms_get",
        "columns": {
            "id": "Room type identifier within the property.",
            "property_id": "Property identifier added from the parent property.",
            "name": "Room type name.",
            "max_people": "Maximum number of guests that the room can accommodate.",
            "units": "Number of units with this room type.",
        },
    },
    "availability": {
        "description": "Availability calendar periods for each property room type, for one year from the sync date.",
        "docs_url": "https://docs.lodgify.com/reference/getcalendarbyuser",
        "columns": {
            "user_id": "Identifier of the Lodgify account that owns the property.",
            "property_id": "Property identifier.",
            "room_type_id": "Room type identifier.",
            "start": "First day of the period.",
            "end": "Last day of the period.",
            "available": "Number of units available in the period.",
            "closed_period": "Closed period that blocks the dates, if any.",
            "bookings": "Bookings that occupy the period, with their status.",
            "channel_calendars": "External channel calendars that block the period.",
        },
    },
    "rates_calendar": {
        "description": "Nightly rates for each property room type, for one year from the sync date.",
        "docs_url": "https://docs.lodgify.com/reference/ratescalendar-v2",
        "columns": {
            "property_id": "Property identifier.",
            "room_type_id": "Room type identifier.",
            "date": "Day that the rates apply to.",
            "is_default": "Whether the day uses the default rate.",
            "prices": "Prices for the day, with minimum stay, maximum stay, and price per extra guest.",
        },
    },
    "external_bookings": {
        "description": "External channel bookings that belong to each booking.",
        "docs_url": "https://docs.lodgify.com/reference/getexternalbookingsasync",
        "columns": {
            "booking_id": "Identifier of the Lodgify booking.",
            "booking_updated_at": "Time of the latest update to the Lodgify booking.",
            "created_at": "Time when the external booking was created.",
            "content": "Contents of the external booking.",
        },
    },
}
