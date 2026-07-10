from dataclasses import dataclass, field


@dataclass
class JobNimbusEndpointConfig:
    name: str
    path: str
    # JobNimbus records carry a globally unique `jnid` (not `id`), so it is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["jnid"])


# JobNimbus Open API top-level list endpoints. All are full-refresh only: while records expose
# `date_created` / `date_updated` epoch fields, the server-side modification filter syntax isn't
# documented well enough to advance an incremental cursor safely, so a client-side scan would cost
# the same as a full refresh (see the implementing-warehouse-sources skill).
JOBNIMBUS_ENDPOINTS: dict[str, JobNimbusEndpointConfig] = {
    "contacts": JobNimbusEndpointConfig(name="contacts", path="/contacts"),
    "jobs": JobNimbusEndpointConfig(name="jobs", path="/jobs"),
    "tasks": JobNimbusEndpointConfig(name="tasks", path="/tasks"),
    "activities": JobNimbusEndpointConfig(name="activities", path="/activities"),
}

ENDPOINTS = tuple(JOBNIMBUS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
