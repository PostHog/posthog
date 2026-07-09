from dataclasses import dataclass, field


@dataclass
class RentCastEndpointConfig:
    name: str
    path: str
    # RentCast assigns each property and listing a stable, globally unique `id`, so it is a safe
    # primary key across full-refresh syncs.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# RentCast v1 list endpoints. All are full-refresh only: RentCast exposes no server-side
# updated-since cursor (listing search only filters by `daysOld`, days since first listed, which
# isn't a last-modified timestamp), so there is no incremental cursor to advance safely.
#
# Only endpoints that return a record list via limit/offset pagination without a mandatory parent
# id are included. RentCast is a property-lookup API, so these search endpoints accept optional
# geographic filters (city/state/zipCode/lat-long) and fall back to a broad default area when none
# is supplied. The single-object market-statistics endpoint (`/markets`) requires a `zipCode` and
# is intentionally omitted.
RENTCAST_ENDPOINTS: dict[str, RentCastEndpointConfig] = {
    "properties": RentCastEndpointConfig(name="properties", path="/properties"),
    "sale_listings": RentCastEndpointConfig(name="sale_listings", path="/listings/sale"),
    "rental_listings": RentCastEndpointConfig(name="rental_listings", path="/listings/rental/long-term"),
}

ENDPOINTS = tuple(RENTCAST_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
