from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType


@dataclass(frozen=False)
class ThinkificEndpointConfig:
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


# List endpoints of the Thinkific public Admin API. Every top-level object carries a numeric `id` that
# is unique within its own collection, so `id` is a safe table-wide primary key. Fan-out children
# aggregate rows across parents, so their keys also carry the parent id.
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
    # Coupons require a promotion_id query param, so they fan out over promotions. The framework
    # only binds resolve params in the path, hence the query string in the path template.
    "coupons": ThinkificEndpointConfig(
        name="coupons",
        path="/coupons?promotion_id={promotion_id}",
        partition_key="created_at",
        primary_keys=["promotion_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="promotions",
            resolve_param="promotion_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "promotion_id"},
        ),
    ),
    "course_reviews": ThinkificEndpointConfig(
        name="course_reviews",
        path="/course_reviews?course_id={course_id}",
        partition_key="created_at",
        primary_keys=["course_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="courses",
            resolve_param="course_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "course_id"},
        ),
    ),
    # Chapter rows carry no course id, so it comes from the parent course.
    "chapters": ThinkificEndpointConfig(
        name="chapters",
        path="/courses/{course_id}/chapters",
        primary_keys=["course_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="courses",
            resolve_param="course_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "course_id"},
        ),
    ),
    # Contents sit two levels below courses. Each course row lists its `chapter_ids`, so the parent
    # course listing is expanded into one row per chapter (see `_course_chapter_rows`) and the
    # fan-out stays single-level.
    "contents": ThinkificEndpointConfig(
        name="contents",
        path="/chapters/{chapter_id}/contents",
        primary_keys=["chapter_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="courses",
            resolve_param="chapter_id",
            resolve_field="chapter_id",
            include_from_parent=["course_id"],
            parent_field_renames={"course_id": "course_id"},
        ),
    ),
}

ENDPOINTS = tuple(THINKIFIC_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in THINKIFIC_ENDPOINTS.items() if config.incremental_fields
}
