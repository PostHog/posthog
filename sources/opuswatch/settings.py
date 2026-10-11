from dataclasses import dataclass

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.opuswatch.nl/ext/"
DEFAULT_START_DATE = "20250101"
PAGE_SIZE = 10000


@dataclass(frozen=True)
class OPUSWatchEndpointConfig:
    name: str
    path: str
    primary_key: str = "id"
    # Stable datetime field used for Delta partitioning; None disables partitioning
    # (master-data tables are small enough not to need it).
    partition_key: str | None = None
    # Transactional endpoints paginate with offset/limit and accept the
    # filter_date_by date-window params; master-data endpoints return the full
    # list (or a single object, for `client`) in one response.
    paginated: bool = False
    supports_date_window: bool = False


OPUSWATCH_ENDPOINTS: dict[str, OPUSWatchEndpointConfig] = {
    # The client endpoint returns the account itself, which has no id field.
    "client": OPUSWatchEndpointConfig(name="client", path="master/client", primary_key="name"),
    "locations": OPUSWatchEndpointConfig(name="locations", path="master/locations"),
    "rows": OPUSWatchEndpointConfig(name="rows", path="master/rows"),
    "users": OPUSWatchEndpointConfig(name="users", path="master/users"),
    "workers": OPUSWatchEndpointConfig(name="workers", path="master/workers"),
    "worker_groups": OPUSWatchEndpointConfig(name="worker_groups", path="master/workergroups"),
    "tasks": OPUSWatchEndpointConfig(name="tasks", path="master/tasks"),
    "task_groups": OPUSWatchEndpointConfig(name="task_groups", path="master/taskgroups"),
    "labels": OPUSWatchEndpointConfig(name="labels", path="master/labels"),
    "varieties": OPUSWatchEndpointConfig(name="varieties", path="master/varieties"),
    "registrations": OPUSWatchEndpointConfig(
        name="registrations",
        path="transactional/registrations",
        partition_key="startTimestamp",
        paginated=True,
        supports_date_window=True,
    ),
    "sessions": OPUSWatchEndpointConfig(
        name="sessions",
        path="transactional/sessions",
        partition_key="startTimestampGross",
        paginated=True,
        supports_date_window=True,
    ),
}

ENDPOINTS = tuple(OPUSWATCH_ENDPOINTS.keys())

# Only the transactional endpoints accept a server-side date-window filter
# (filter_date_by=UPDATED); master-data endpoints are full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "registrations": [incremental_field("updatedTimestamp")],
    "sessions": [incremental_field("updatedTimestamp")],
}
