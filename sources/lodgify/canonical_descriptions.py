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
}
