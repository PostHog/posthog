from dataclasses import dataclass, field


@dataclass
class OncehubEndpointConfig:
    name: str
    path: str
    # OnceHub object IDs are prefixed strings (BKNG-, CTC-, USR-, TM-, BKC-) that are unique
    # across the account, so `id` is a safe primary key for every endpoint.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# OnceHub Booking Calendars API (v2) list endpoints. All are full refresh only: the API's
# `last_updated_time.gt` filters are date-granular and list results paginate by object-ID cursor
# in reverse-chronological order, so there is no reliable server-side incremental cursor to
# advance safely without verified ordering guarantees.
ONCEHUB_ENDPOINTS: dict[str, OncehubEndpointConfig] = {
    "bookings": OncehubEndpointConfig(name="bookings", path="/bookings"),
    "booking_calendars": OncehubEndpointConfig(name="booking_calendars", path="/booking-calendars"),
    "contacts": OncehubEndpointConfig(name="contacts", path="/contacts"),
    "users": OncehubEndpointConfig(name="users", path="/users"),
    "teams": OncehubEndpointConfig(name="teams", path="/teams"),
}

ENDPOINTS = tuple(ONCEHUB_ENDPOINTS.keys())
