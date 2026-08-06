from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField

# How records are laid out in a BambooHR JSON response.
#   "list" — the records are a JSON array (either the whole body or under ``data_key``)
#   "dict" — the records are a JSON object keyed by id (e.g. ``meta/users``); we take ``.values()``
DataShape = Literal["list", "dict"]


@dataclass
class BambooHREndpointConfig:
    name: str
    # Path relative to ``/api/gateway.php/{subdomain}/v1/``.
    path: str
    primary_keys: list[str]
    # JSON key holding the records, or ``None`` when the body itself is the collection.
    data_key: str | None = None
    data_shape: DataShape = "list"
    # Some endpoints (time off) reject requests without an explicit date window.
    requires_date_window: bool = False
    # No BambooHR endpoint we ship exposes a verified server-side "modified since" filter
    # that also returns full records, so every stream is full-refresh for now. See bamboohr.py.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


BAMBOOHR_ENDPOINTS: dict[str, BambooHREndpointConfig] = {
    "employees": BambooHREndpointConfig(
        name="employees",
        path="employees/directory",
        data_key="employees",
        primary_keys=["id"],
    ),
    "time_off_requests": BambooHREndpointConfig(
        name="time_off_requests",
        path="time_off/requests",
        primary_keys=["id"],
        requires_date_window=True,
    ),
    "time_off_types": BambooHREndpointConfig(
        name="time_off_types",
        path="meta/time_off/types",
        data_key="timeOffTypes",
        primary_keys=["id"],
    ),
    "meta_fields": BambooHREndpointConfig(
        name="meta_fields",
        path="meta/fields",
        primary_keys=["id"],
    ),
    "meta_lists": BambooHREndpointConfig(
        name="meta_lists",
        path="meta/lists",
        primary_keys=["fieldId"],
    ),
    "meta_users": BambooHREndpointConfig(
        name="meta_users",
        path="meta/users",
        data_shape="dict",
        primary_keys=["id"],
    ),
}

ENDPOINTS = tuple(BAMBOOHR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BAMBOOHR_ENDPOINTS.items()
}
