import dataclasses


@dataclasses.dataclass(frozen=True)
class AviationstackEndpointConfig:
    name: str
    path: str
    # aviationstack reference tables expose a stable row `id`; the flight/route feeds do not (each
    # record is a nested flight document with no top-level identifier), so those sync as keyless full
    # refresh snapshots.
    primary_keys: list[str] | None
    description: str | None = None
    # `/timetable` and `/flightsFuture` are per-airport feeds: each request must name one airport
    # and one schedule type, so they fan out over the airport IATA codes configured on the source.
    per_airport: bool = False
    # `/flightsFuture` additionally requires a date, so it fans out over a lookahead window too.
    needs_date: bool = False
    # aviationstack throttles the per-airport feeds far harder than the rest of the API
    # (1 request/10s on paid plans, 1 request/60s on free ones).
    throttled: bool = False


# aviationstack has no record-level updated-at cursor (the `flight_date` filter is a per-day window
# limited to ~3 months, not a true incremental cursor), so every endpoint is full refresh.
AVIATIONSTACK_ENDPOINTS: dict[str, AviationstackEndpointConfig] = {
    "flights": AviationstackEndpointConfig(
        name="flights",
        path="/flights",
        primary_keys=None,
        description="Real-time and recent flight status, including departure, arrival, airline, and live position. Full refresh snapshot.",
    ),
    "timetable": AviationstackEndpointConfig(
        name="timetable",
        path="/timetable",
        primary_keys=None,
        per_airport=True,
        throttled=True,
        description="Live departure and arrival schedules for the configured airports, with terminal, gate, delay, and status. Full refresh snapshot.",
    ),
    "flights_future": AviationstackEndpointConfig(
        name="flights_future",
        path="/flightsFuture",
        primary_keys=None,
        per_airport=True,
        needs_date=True,
        throttled=True,
        description="Future scheduled departures and arrivals for the configured airports, one request per lookahead date. Full refresh snapshot.",
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

# Both per-airport feeds serve one schedule direction per request.
SCHEDULE_TYPES = ("departure", "arrival")

# aviationstack only serves /flightsFuture for dates more than 7 days out, so day 8 is the first
# date we can ask for. The window is bounded because every extra day is another request per airport
# and schedule type against an endpoint that allows one request every 10 seconds.
FLIGHTS_FUTURE_FIRST_DAY_AHEAD = 8
FLIGHTS_FUTURE_DEFAULT_DAYS = 7
FLIGHTS_FUTURE_MAX_DAYS = 30

# Bounds the per-airport fan-out so one oversized airport list cannot stall a sync indefinitely.
MAX_AIRPORTS = 25
