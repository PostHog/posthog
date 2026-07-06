from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Workable caps `limit` at 100 (default 50) across the list endpoints.
PAGE_SIZE = 100


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class WorkableEndpointConfig:
    name: str
    # Path under the `/spi/v3` base (e.g. `/jobs`).
    path: str
    # Key the result array is nested under in the JSON response (e.g. `{"jobs": [...]}`).
    data_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation timestamp used for datetime partitioning. Never `updated_at` — partitions
    # must not rewrite on every sync. `None` when the resource has no creation timestamp.
    partition_key: Optional[str] = None
    # Only `True` when the endpoint exposes a genuine server-side `<field>_after` time filter.
    supports_incremental: bool = False


# Account-level list endpoints. These mirror the canonical Workable connector stream set
# (jobs, candidates, members, recruiters, stages). All return `{<data_key>: [...]}` and the
# paginated ones carry a sibling `{"paging": {"next": "<full url>"}}`.
WORKABLE_ENDPOINTS: dict[str, WorkableEndpointConfig] = {
    "jobs": WorkableEndpointConfig(
        name="jobs",
        path="/jobs",
        data_key="jobs",
        primary_keys=["id"],
        partition_key="created_at",
        supports_incremental=True,
        incremental_fields=[_datetime_field("updated_at"), _datetime_field("created_at")],
    ),
    "candidates": WorkableEndpointConfig(
        name="candidates",
        path="/candidates",
        data_key="candidates",
        primary_keys=["id"],
        partition_key="created_at",
        supports_incremental=True,
        incremental_fields=[_datetime_field("updated_at"), _datetime_field("created_at")],
    ),
    # Members, recruiters, and stages are small account-level reference collections with no
    # server-side time filter (and stages/recruiters have no pagination at all), so they're
    # full refresh only.
    "members": WorkableEndpointConfig(
        name="members",
        path="/members",
        data_key="members",
        primary_keys=["id"],
    ),
    "recruiters": WorkableEndpointConfig(
        name="recruiters",
        path="/recruiters",
        data_key="recruiters",
        primary_keys=["id"],
    ),
    # Stages are keyed by `slug` — the stage object has no `id`.
    "stages": WorkableEndpointConfig(
        name="stages",
        path="/stages",
        data_key="stages",
        primary_keys=["slug"],
    ),
}

ENDPOINTS = tuple(WORKABLE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in WORKABLE_ENDPOINTS.items()
}
