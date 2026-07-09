from dataclasses import dataclass, field


@dataclass
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


# Cloudbeds PMS API v1.2 list endpoints. All are full refresh only for now: getReservations
# documents a server-side `modifiedSince` filter, but Cloudbeds notes some reservation
# modifications are not reflected in the modified timestamp, and we have not been able to verify
# the filter's behavior against a live account - so we conservatively ship full refresh and dedupe
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
}

ENDPOINTS = tuple(CLOUDBEDS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
