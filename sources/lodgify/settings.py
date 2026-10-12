from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.lodgify.com/v2/"
PAGE_SIZE = 50
ENDPOINTS = ("properties", "bookings", "rooms")
PATHS = {"properties": "properties", "bookings": "reservations/bookings", "rooms": "properties/{id}/rooms"}
PRIMARY_KEYS = {"properties": ["id"], "bookings": ["id"], "rooms": ["property_id", "id"]}
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "field": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field_type": IncrementalFieldType.DateTime,
            "label": "updated_at",
        }
    ]
    for name in ("properties", "bookings")
}
AUTH_ERROR = "Lodgify rejected the API key. Copy your key from Settings > Public API and reconnect."
PERMISSION_ERROR = "Lodgify denied access. Check your account's API access and reconnect."
