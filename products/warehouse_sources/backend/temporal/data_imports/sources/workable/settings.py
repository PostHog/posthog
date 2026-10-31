from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
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


@dataclass(frozen=False)
class WorkableEndpointConfig:
    name: str
    # Path under the `/spi/v3` base (e.g. `/jobs`).
    path: str
    # Key the result array is nested under in the JSON response (e.g. `{"jobs": [...]}`). `None`
    # when the response body is the array itself.
    data_key: Optional[str]
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation timestamp used for datetime partitioning. Never `updated_at` — partitions
    # must not rewrite on every sync. `None` when the resource has no creation timestamp.
    partition_key: Optional[str] = None
    # Only `True` when the endpoint exposes a genuine server-side `<field>_after` time filter.
    supports_incremental: bool = False
    # `next_url` follows `paging.next`, `offset` walks `offset`/`limit` against `totalCount`, and
    # `none` is a single unpaginated request.
    pagination: Literal["next_url", "offset", "none"] = "next_url"
    page_size: int = PAGE_SIZE
    default_incremental_field: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None


# Account-level list endpoints plus the candidate activity fan-out. Most return
# `{<data_key>: [...]}` and the paginated ones carry a sibling `{"paging": {"next": "<full url>"}}`.
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
    # Requires the `r_account` scope and Workable's employee management features. The response is
    # a bare array with no pagination.
    "departments": WorkableEndpointConfig(
        name="departments",
        path="/departments",
        data_key=None,
        primary_keys=["id"],
        pagination="none",
    ),
    # Requires the `r_employees` scope. An account-level token only sees published employees.
    # There is no server-side time filter, so this is full refresh only.
    "employees": WorkableEndpointConfig(
        name="employees",
        path="/employees",
        data_key="employees",
        primary_keys=["id"],
        pagination="offset",
    ),
    # Activities have no list endpoint of their own, so they fan out over every candidate. The docs
    # list no activity id, so the key is the parent candidate plus the activity's creation time and
    # action.
    "candidate_activities": WorkableEndpointConfig(
        name="candidate_activities",
        path="/candidates/{id}/activities",
        data_key="activities",
        primary_keys=["candidate_id", "created_at", "action"],
        partition_key="created_at",
        supports_incremental=True,
        incremental_fields=[_datetime_field("updated_at")],
        default_incremental_field="updated_at",
        fanout=DependentEndpointConfig(
            parent_name="candidates",
            resolve_param="id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "candidate_id"},
            # A candidate deleted between the parent listing and its activity fetch answers 404.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(WORKABLE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in WORKABLE_ENDPOINTS.items()
}
