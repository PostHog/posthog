import dataclasses


@dataclasses.dataclass
class AviationstackEndpointConfig:
    name: str
    path: str
    # aviationstack reference tables expose a stable row `id`; the flight/route feeds do not (each
    # record is a nested flight document with no top-level identifier), so those sync as keyless full
    # refresh snapshots.
    primary_keys: list[str] | None
    description: str | None = None


# aviationstack has no record-level updated-at cursor (the `flight_date` filter is a per-day window
# limited to ~3 months, not a true incremental cursor), so every endpoint is full refresh.
AVIATIONSTACK_ENDPOINTS: dict[str, AviationstackEndpointConfig] = {
    "flights": AviationstackEndpointConfig(
        name="flights",
        path="/flights",
        primary_keys=None,
        description="Real-time and recent flight status, including departure, arrival, airline, and live position. Full refresh snapshot.",
    ),
    "routes": AviationstackEndpointConfig(
        name="routes",
        path="/routes",
        primary_keys=None,
        description="Scheduled airline routes with departure, arrival, airline, and flight details. Full refresh snapshot.",
    ),
    "airports": AviationstackEndpointConfig(
        name="airports",
        path="/airports",
        primary_keys=["id"],
        description="Reference table of airports with IATA/ICAO codes, location, and timezone.",
    ),
    "airlines": AviationstackEndpointConfig(
        name="airlines",
        path="/airlines",
        primary_keys=["id"],
        description="Reference table of airlines with IATA/ICAO codes, fleet, and status.",
    ),
    "airplanes": AviationstackEndpointConfig(
        name="airplanes",
        path="/airplanes",
        primary_keys=["id"],
        description="Reference table of individual aircraft with registration, model, and operator details.",
    ),
    "aircraft_types": AviationstackEndpointConfig(
        name="aircraft_types",
        path="/aircraft_types",
        primary_keys=["id"],
        description="Reference table of aircraft types with IATA codes.",
    ),
    "cities": AviationstackEndpointConfig(
        name="cities",
        path="/cities",
        primary_keys=["id"],
        description="Reference table of cities with IATA codes, location, and timezone.",
    ),
    "countries": AviationstackEndpointConfig(
        name="countries",
        path="/countries",
        primary_keys=["id"],
        description="Reference table of countries with ISO codes, currency, and population.",
    ),
    "taxes": AviationstackEndpointConfig(
        name="taxes",
        path="/taxes",
        primary_keys=["id"],
        description="Reference table of aviation taxes with names and IATA codes.",
    ),
}

ENDPOINTS = tuple(AVIATIONSTACK_ENDPOINTS.keys())
