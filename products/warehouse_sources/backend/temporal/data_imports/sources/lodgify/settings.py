from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.lodgify.com/v2/"
PAGE_SIZE = 50
# The availability and rates calendars need a date range; sync a rolling year from today.
CALENDAR_WINDOW_DAYS = 365
ENDPOINTS = ("properties", "bookings", "rooms", "availability", "rates_calendar", "external_bookings")
PATHS = {
    "properties": "properties",
    "bookings": "reservations/bookings",
    "rooms": "properties/{id}/rooms",
    "availability": "availability",
    "rates_calendar": "rates/calendar?HouseId={HouseId}&RoomTypeId={RoomTypeId}",
    "external_bookings": "reservations/bookings/{id}/externalBookings",
}
PRIMARY_KEYS = {
    "properties": ["id"],
    "bookings": ["id"],
    "rooms": ["property_id", "id"],
    "availability": ["property_id", "room_type_id", "start"],
    "rates_calendar": ["property_id", "room_type_id", "date"],
    "external_bookings": ["booking_id", "created_at"],
}


def _incremental_field(field: str) -> list[IncrementalField]:
    return [
        {
            "field": field,
            "type": IncrementalFieldType.DateTime,
            "field_type": IncrementalFieldType.DateTime,
            "label": field,
        }
    ]


INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "properties": _incremental_field("updated_at"),
    "bookings": _incremental_field("updated_at"),
    "external_bookings": _incremental_field("booking_updated_at"),
}
AUTH_ERROR = "Lodgify rejected the API key. Copy your key from Settings > Public API and reconnect."
PERMISSION_ERROR = "Lodgify denied access. Check your account's API access and reconnect."
