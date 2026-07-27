from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ThinkificEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Thinkific only exposes server-side date filters (query[updated_*]) on a subset of its list
    # endpoints. When False the endpoint is full refresh regardless of any advertised incremental
    # fields, so we never pretend to filter server-side when the API would silently ignore it.
    supports_incremental: bool = False
    # Stable creation timestamp used for datetime partitioning. Only set where the field is
    # confirmed to exist in the response payload (verified against the Thinkific API docs); leaving
    # it None disables partitioning rather than risk partitioning on an absent column.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Default page size is 25; the API accepts a larger limit. 100 divides evenly into the
    # pipeline's batch thresholds, keeping resume checkpoints on clean page boundaries.
    page_size: int = 100


_UPDATED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "updated_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


# Top-level (account-scoped) list endpoints of the Thinkific public Admin API. Every object carries a
# numeric `id` that is unique within its own collection, so `id` is a safe table-wide primary key
# (these are not fan-out children that aggregate rows across parents).
THINKIFIC_ENDPOINTS: dict[str, ThinkificEndpointConfig] = {
    "courses": ThinkificEndpointConfig(name="courses", path="/courses"),
    "collections": ThinkificEndpointConfig(name="collections", path="/collections"),
    # Enrollments is the one endpoint the API documents server-side date filtering for
    # (query[updated_after] / query[updated_on_or_after] / ...), so it's the only incremental one.
    "enrollments": ThinkificEndpointConfig(
        name="enrollments",
        path="/enrollments",
        supports_incremental=True,
        partition_key="created_at",
        incremental_fields=_UPDATED_AT_INCREMENTAL,
    ),
    "users": ThinkificEndpointConfig(name="users", path="/users", partition_key="created_at"),
    "instructors": ThinkificEndpointConfig(name="instructors", path="/instructors"),
    "orders": ThinkificEndpointConfig(name="orders", path="/orders"),
    "products": ThinkificEndpointConfig(name="products", path="/products"),
    "promotions": ThinkificEndpointConfig(name="promotions", path="/promotions"),
    "groups": ThinkificEndpointConfig(name="groups", path="/groups"),
}

ENDPOINTS = tuple(THINKIFIC_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in THINKIFIC_ENDPOINTS.items() if config.incremental_fields
}
