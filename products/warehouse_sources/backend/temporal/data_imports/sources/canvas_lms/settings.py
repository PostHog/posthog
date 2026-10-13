from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Canvas caps per_page well above its documented default of 10; institutions can have thousands of
# courses/users/submissions, so request the largest page the API accepts.
PAGE_SIZE = 100

# Submissions fan out per course. The Submission object carries no `course_id`, so the fan-out
# helper injects the parent course id under this rename.
_COURSE_FANOUT = DependentEndpointConfig(
    parent_name="courses",
    resolve_param="course_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "course_id"},
)


# Mutable by choice, not oversight: instances flow into `build_dependent_resource`'s
# `endpoint_configs: Mapping[str, FanoutEndpointLike]`, and mypy treats a frozen dataclass's
# fields as read-only, which is incompatible with that Protocol's plain (read-write) attributes.
@dataclass(frozen=False)
class CanvasEndpointConfig:
    name: str
    path: str  # relative to /api/v1
    primary_keys: list[str]
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Maps an advertised incremental field name to the query param Canvas actually filters on
    # for it (e.g. `submitted_at` -> `submitted_since`).
    incremental_query_params: dict[str, str] = field(default_factory=dict)
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE


CANVAS_ENDPOINTS: dict[str, CanvasEndpointConfig] = {
    # Account-level listing requires an account admin token; there is no documented
    # `updated_since`-style filter, so this is full refresh every sync.
    "courses": CanvasEndpointConfig(
        name="courses",
        path="/accounts/{account_id}/courses",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "users": CanvasEndpointConfig(
        name="users",
        path="/accounts/{account_id}/users",
        primary_keys=["id"],
    ),
    # `id` is unique per enrollment but the docs don't state whether it's globally unique across
    # the install, so `course_id` (a native field on the Enrollment object) is kept in the key.
    "enrollments": CanvasEndpointConfig(
        name="enrollments",
        path="/courses/{course_id}/enrollments",
        primary_keys=["id", "course_id"],
        partition_key="created_at",
        fanout=_COURSE_FANOUT,
    ),
    # No documented `updated_since` filter for this endpoint, despite the Assignment object
    # exposing `updated_at` -- full refresh only.
    "assignments": CanvasEndpointConfig(
        name="assignments",
        path="/courses/{course_id}/assignments",
        primary_keys=["id", "course_id"],
        partition_key="created_at",
        fanout=_COURSE_FANOUT,
    ),
    # `assignment_id` + `user_id` is unique per submission by Canvas's data model (one submission
    # per student per assignment) regardless of course, so no parent id is needed in the key.
    "submissions": CanvasEndpointConfig(
        name="submissions",
        path="/courses/{course_id}/students/submissions",
        primary_keys=["assignment_id", "user_id"],
        incremental_fields=[incremental_field("submitted_at"), incremental_field("graded_at")],
        default_incremental_field="submitted_at",
        incremental_query_params={"submitted_at": "submitted_since", "graded_at": "graded_since"},
        fanout=DependentEndpointConfig(
            parent_name="courses",
            resolve_param="course_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "course_id"},
            # `student_ids[]=all` returns every student's submissions rather than just the
            # caller's own. `order=id` matches the endpoint's documented default explicitly, so
            # pagination stays stable even if Canvas ever changes that default.
            child_params={"student_ids[]": "all", "order": "id", "order_direction": "ascending"},
        ),
    ),
}

ENDPOINTS = tuple(CANVAS_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CANVAS_ENDPOINTS.items()
}
