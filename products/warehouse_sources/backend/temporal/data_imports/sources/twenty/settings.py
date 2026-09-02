from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Twenty's core REST list endpoints cap `limit` at 200 (`QUERY_MAX_RECORDS` server-side, verified
# against the REST request parser source); the documented default is 60. Requesting the max keeps
# request counts low.
PAGE_SIZE = 200

# (connect, read) timeout in seconds. The base URL is customer-controlled, so an unbounded read
# lets a host that stalls mid-response hold an import worker until the week-long activity timeout.
REQUEST_TIMEOUT: tuple[float, float] = (10.0, 60.0)

# Every Twenty workspace entity carries `createdAt` / `updatedAt`, so both are offered as
# incremental candidates on every endpoint; `updatedAt` also catches later edits.
_INCREMENTAL_FIELDS: list[IncrementalField] = [
    incremental_field("updatedAt"),
    incremental_field("createdAt"),
]


@frozen
class TwentyEndpointConfig:
    name: str
    # REST path segment (the object's `namePlural`), appended to the configured base URL.
    path: str
    primary_key: str = "id"
    partition_key: str = "createdAt"
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_INCREMENTAL_FIELDS))


# Twenty's REST API is schema-per-workspace and lets users add custom objects, but every
# workspace ships these standard CRM objects, so they're the safe, verified sync targets rather
# than a metadata-driven discovery of custom objects (whose REST list response shape varies by an
# internal, unverifiable feature flag — see the module docstring in twenty.py). `activities` maps
# to Twenty's `timelineActivities` object, the audit trail of record events shown on a record's
# timeline.
TWENTY_ENDPOINTS: dict[str, TwentyEndpointConfig] = {
    "companies": TwentyEndpointConfig(name="companies", path="/companies"),
    "people": TwentyEndpointConfig(name="people", path="/people"),
    "opportunities": TwentyEndpointConfig(name="opportunities", path="/opportunities"),
    "notes": TwentyEndpointConfig(name="notes", path="/notes"),
    "tasks": TwentyEndpointConfig(name="tasks", path="/tasks"),
    "activities": TwentyEndpointConfig(name="activities", path="/timelineActivities"),
}

ENDPOINTS = tuple(TWENTY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TWENTY_ENDPOINTS.items()
}
