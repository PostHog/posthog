import dataclasses
from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField

# Clockodo versions its endpoints per resource rather than per account, so the source-level
# label is opaque: "v2" is the pre-2026-05 endpoint set; "v3" is the post-deprecation set that
# routes each resource to its non-deprecated successor (a mix of the vendor's v3 and v4 routes).
# On 2026-05-01 Clockodo decommissions the v2 endpoints behind six of our tables
# (https://www.clockodo.com/en/blog/deprecation-of-legacy-api-endpoints-on-may-1-2026/), so a
# "v2"-pinned source keeps working only until then; "v3" is the migration target.
CLOCKODO_API_VERSION_V2 = "v2"
CLOCKODO_API_VERSION_V3 = "v3"
CLOCKODO_SUPPORTED_VERSIONS = (CLOCKODO_API_VERSION_V2, CLOCKODO_API_VERSION_V3)
CLOCKODO_DEFAULT_API_VERSION = CLOCKODO_API_VERSION_V3


@dataclass
class ClockodoEndpointConfig:
    name: str  # schema name shown to the user (matches the warehouse table)
    path: str  # API path relative to the base URL, e.g. "v2/customers"
    data_key: str  # key in the JSON response body that holds the list of rows
    # Clockodo only paginates a subset of resources (entries, entriesTexts, customers,
    # projects). The rest return the full collection in a single response with no paging block.
    # Every v3/v4 collection paginates, so the successor configs flip this on.
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


CLOCKODO_ENDPOINTS_V2: dict[str, ClockodoEndpointConfig] = {
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


def _v3(config: ClockodoEndpointConfig, path: str) -> ClockodoEndpointConfig:
    """Successor config for a resource whose v2 endpoint is decommissioned on 2026-05-01.

    The v3/v4 collections return their rows under a uniform "data" key (v2 used the resource
    name) and paginate every collection, so only the wire fields change; the table name,
    primary key, description, and sync default carry over from the v2 config.
    """
    return dataclasses.replace(config, path=path, data_key="data", paginated=True)


# v3 reuses the v2 configs for the two resources Clockodo did not decommission (surcharges,
# entries) and points the other six at their v3/v4 successors from the deprecation notice.
CLOCKODO_ENDPOINTS_V3: dict[str, ClockodoEndpointConfig] = {
    **CLOCKODO_ENDPOINTS_V2,
    "customers": _v3(CLOCKODO_ENDPOINTS_V2["customers"], "v3/customers"),
    "projects": _v3(CLOCKODO_ENDPOINTS_V2["projects"], "v4/projects"),
    "services": _v3(CLOCKODO_ENDPOINTS_V2["services"], "v4/services"),
    "lumpsum_services": _v3(CLOCKODO_ENDPOINTS_V2["lumpsum_services"], "v4/lumpSumServices"),
    "users": _v3(CLOCKODO_ENDPOINTS_V2["users"], "v3/users"),
    "teams": _v3(CLOCKODO_ENDPOINTS_V2["teams"], "v3/teams"),
}

CLOCKODO_ENDPOINTS_BY_VERSION: dict[str, dict[str, ClockodoEndpointConfig]] = {
    CLOCKODO_API_VERSION_V2: CLOCKODO_ENDPOINTS_V2,
    CLOCKODO_API_VERSION_V3: CLOCKODO_ENDPOINTS_V3,
}


def endpoints_for_version(api_version: str) -> dict[str, ClockodoEndpointConfig]:
    """Per-resource endpoint map for a supported version.

    Raises on a label outside `CLOCKODO_SUPPORTED_VERSIONS` rather than falling through to a
    default, because silently routing an unknown pin to the wrong paths is the drift this
    framework prevents. Callers resolve None to the default before this, so an unknown label
    here means a deliberate but undeclared DB pin, which is a misconfiguration to surface.
    """
    try:
        return CLOCKODO_ENDPOINTS_BY_VERSION[api_version]
    except KeyError as e:
        raise ValueError(
            f"Unsupported Clockodo API version {api_version!r}; supported: {CLOCKODO_SUPPORTED_VERSIONS}"
        ) from e


# The table set is identical across versions, so discovery never orphans a table on repin.
ENDPOINTS = tuple(CLOCKODO_ENDPOINTS_V2.keys())

# Clockodo exposes no server-side "modified since" filter on any resource (time_last_change is
# returned but not filterable), so every table is full refresh only — no incremental fields.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ENDPOINTS}
