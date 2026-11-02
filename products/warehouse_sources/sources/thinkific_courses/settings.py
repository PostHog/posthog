from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ThinkificCoursesEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
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
    # Set for child endpoints that iterate a parent list and query per parent (single-level fan-out).
    fanout: Optional[DependentEndpointConfig] = None


_UPDATED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "updated_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


# List endpoints of the Thinkific public Admin API (https://api.thinkific.com/api/public/v1). Every
# top-level object carries a numeric `id` unique within its own collection, so `id` is a safe
# table-wide primary key there. Fan-out children aggregate rows across parents, so their key
# includes the parent id — Thinkific doesn't document child ids as globally unique.
THINKIFIC_COURSES_ENDPOINTS: dict[str, ThinkificCoursesEndpointConfig] = {
    "courses": ThinkificCoursesEndpointConfig(name="courses", path="/courses"),
    "collections": ThinkificCoursesEndpointConfig(name="collections", path="/collections"),
    # The reviews endpoint requires a course_id query param, so it fans out over courses. The
    # framework only binds resolve params in the path, hence the query string in the path template.
    "course_reviews": ThinkificCoursesEndpointConfig(
        name="course_reviews",
        path="/course_reviews?course_id={course_id}",
        primary_keys=["course_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="courses",
            resolve_param="course_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "course_id"},
        ),
    ),
    # Coupons require a promotion_id query param, so they fan out over promotions.
    "coupons": ThinkificCoursesEndpointConfig(
        name="coupons",
        path="/coupons?promotion_id={promotion_id}",
        primary_keys=["promotion_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="promotions",
            resolve_param="promotion_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "promotion_id"},
        ),
    ),
    # Enrollments is the one endpoint the API documents server-side date filtering for
    # (query[updated_after] / query[updated_on_or_after] / ...), so it's the only incremental one.
    "enrollments": ThinkificCoursesEndpointConfig(
        name="enrollments",
        path="/enrollments",
        supports_incremental=True,
        partition_key="created_at",
        incremental_fields=_UPDATED_AT_INCREMENTAL,
        default_incremental_field="updated_at",
    ),
    "groups": ThinkificCoursesEndpointConfig(name="groups", path="/groups"),
    "instructors": ThinkificCoursesEndpointConfig(name="instructors", path="/instructors"),
    "orders": ThinkificCoursesEndpointConfig(name="orders", path="/orders"),
    "products": ThinkificCoursesEndpointConfig(name="products", path="/products"),
    "promotions": ThinkificCoursesEndpointConfig(name="promotions", path="/promotions"),
    "users": ThinkificCoursesEndpointConfig(name="users", path="/users", partition_key="created_at"),
}

ENDPOINTS = tuple(THINKIFIC_COURSES_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in THINKIFIC_COURSES_ENDPOINTS.items() if config.incremental_fields
}
