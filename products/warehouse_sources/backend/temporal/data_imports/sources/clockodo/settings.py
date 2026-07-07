from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class ClockodoEndpointConfig:
    name: str  # schema name shown to the user (matches the warehouse table)
    path: str  # API path relative to the base URL, e.g. "v2/customers"
    data_key: str  # key in the JSON response body that holds the list of rows
    # Clockodo only paginates a subset of resources (entries, entriesTexts, customers,
    # projects). The rest return the full collection in a single response with no paging block.
    paginated: bool = False
    # Static query params required by the endpoint (e.g. the entries time window).
    extra_params: dict[str, str] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    description: str | None = None


# The /v2/entries list endpoint rejects requests without a time range, so we send a wide
# fixed window that covers all historical entries. time_until is widened past "now" at request
# time to also capture future-dated (planned) entries. ISO 8601 UTC, as the API requires.
ENTRIES_TIME_SINCE = "2000-01-01T00:00:00Z"


CLOCKODO_ENDPOINTS: dict[str, ClockodoEndpointConfig] = {
    "customers": ClockodoEndpointConfig(
        name="customers",
        path="v2/customers",
        data_key="customers",
        paginated=True,
    ),
    "projects": ClockodoEndpointConfig(
        name="projects",
        path="v2/projects",
        data_key="projects",
        paginated=True,
    ),
    "services": ClockodoEndpointConfig(
        name="services",
        path="v2/services",
        data_key="services",
    ),
    "lumpsum_services": ClockodoEndpointConfig(
        name="lumpsum_services",
        path="v2/lumpsumservices",
        data_key="lumpSumServices",
    ),
    "users": ClockodoEndpointConfig(
        name="users",
        path="v2/users",
        data_key="users",
    ),
    "teams": ClockodoEndpointConfig(
        name="teams",
        path="v2/teams",
        data_key="teams",
    ),
    "surcharges": ClockodoEndpointConfig(
        name="surcharges",
        path="v2/surcharges",
        data_key="surcharges",
    ),
    "entries": ClockodoEndpointConfig(
        name="entries",
        path="v2/entries",
        data_key="entries",
        paginated=True,
        description="Time entries across the full account history. Full refresh only — the API "
        "has no server-side modified-since filter.",
    ),
}

ENDPOINTS = tuple(CLOCKODO_ENDPOINTS.keys())

# Clockodo exposes no server-side "modified since" filter on any resource (time_last_change is
# returned but not filterable), so every table is full refresh only — no incremental fields.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in CLOCKODO_ENDPOINTS}
