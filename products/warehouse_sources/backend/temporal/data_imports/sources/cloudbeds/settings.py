from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField


@dataclass(frozen=True)
class CloudbedsEndpointConfig:
    name: str
    path: str
    # Cloudbeds identifiers (reservationID, guestID, roomID, ...) are documented as unique across the
    # account the credential is scoped to, so a single ID field is a safe primary key per endpoint.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Endpoints that accept pageNumber/pageSize. Non-paginated endpoints return the full collection
    # in one response.
    paginated: bool = True
    # Some endpoints group rows under a nested list per property (e.g. getRooms returns one object
    # per property with a `rooms` array). When set, each nested row is emitted as its own row with
    # the parent's fields from `flatten_parent_fields` copied in.
    flatten_field: str | None = None
    flatten_parent_fields: list[str] = field(default_factory=list)
    # Endpoints whose `data` is an object keyed by property ID, with that property's rows in a list
    # under the key (getUsers). Each nested row is emitted with the key copied into this field.
    keyed_by_field: str | None = None
    # Query parameter the configured property ID is sent under. Most methods take `propertyID`; a
    # few take a comma-separated list under their own spelling.
    property_param: str = "propertyID"
    # getRatePlans requires a stay window, so requests cover today through today plus this many
    # days. `None` leaves the endpoint unwindowed.
    stay_window_days: int | None = None


# getRatePlans prices a stay, so it needs a window. A rolling month forward covers the rate plans a
# property currently sells without making the request depend on how far ahead it takes bookings.
RATE_PLAN_WINDOW_DAYS = 30

# Cloudbeds PMS API list endpoints (identical method set across v1.2 and v1.3, which differ only
# by the `/api/<version>` URL segment). All are full refresh only for now: the reservation
# endpoints document server-side modification-date filters, but Cloudbeds notes some reservation
# modifications are not reflected in the modified timestamp, and we have not been able to verify
# the filters' behavior against a live account - so we conservatively ship full refresh and dedupe
# on primary keys (see the implementing-warehouse-sources skill).
CLOUDBEDS_ENDPOINTS: dict[str, CloudbedsEndpointConfig] = {
    "hotels": CloudbedsEndpointConfig(
        name="hotels",
        path="/getHotels",
        primary_keys=["propertyID"],
        paginated=False,
    ),
    "reservations": CloudbedsEndpointConfig(
        name="reservations",
        path="/getReservations",
        primary_keys=["reservationID"],
    ),
    "guests": CloudbedsEndpointConfig(
        name="guests",
        path="/getGuestList",
        primary_keys=["guestID"],
    ),
    "rooms": CloudbedsEndpointConfig(
        name="rooms",
        path="/getRooms",
        primary_keys=["roomID"],
        paginated=False,
        flatten_field="rooms",
        flatten_parent_fields=["propertyID"],
    ),
    "room_types": CloudbedsEndpointConfig(
        name="room_types",
        path="/getRoomTypes",
        primary_keys=["roomTypeID"],
    ),
    "transactions": CloudbedsEndpointConfig(
        name="transactions",
        path="/getTransactions",
        primary_keys=["transactionID"],
    ),
    "reservations_with_rate_details": CloudbedsEndpointConfig(
        name="reservations_with_rate_details",
        path="/getReservationsWithRateDetails",
        primary_keys=["reservationID"],
    ),
    # getRatePlans returns one row per rate, and a rate belongs to exactly one room type, so rateID
    # identifies the row. The rate and availability columns describe the requested window; the rate
    # plan identifiers and configuration are what resolves the rate IDs carried on reservations.
    "rate_plans": CloudbedsEndpointConfig(
        name="rate_plans",
        path="/getRatePlans",
        primary_keys=["rateID"],
        paginated=False,
        property_param="propertyIDs",
        stay_window_days=RATE_PLAN_WINDOW_DAYS,
    ),
    # A user can hold a role at more than one property in a group account, and the response lists
    # them once per property, so the property is part of the key.
    "users": CloudbedsEndpointConfig(
        name="users",
        path="/getUsers",
        primary_keys=["propertyID", "userID"],
        paginated=False,
        property_param="property_ids",
        keyed_by_field="propertyID",
    ),
}

ENDPOINTS = tuple(CLOUDBEDS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
