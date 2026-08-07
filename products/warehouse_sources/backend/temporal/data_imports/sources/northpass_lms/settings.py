from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Northpass exposes no server-side timestamp filter (list endpoints only accept page/limit/q and a
# fixed default sort), so every endpoint is full refresh only — there is no reliable incremental
# cursor. See `northpass_lms.py` for the pagination transport.


@dataclass
class NorthpassEndpointConfig:
    name: str
    # JSON:API collection path relative to the API base. Fan-out children use a `{parent_id}`
    # placeholder resolved per parent resource.
    path: str
    # Stable creation-time field used for datetime partitioning. Never `updated_at` — it moves and
    # would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # For fan-out endpoints: the parent endpoint name to iterate for `{parent_id}`, and the column
    # name under which the parent id is injected into each child row (also part of the primary key).
    fan_out_parent: Optional[str] = None
    parent_id_field: Optional[str] = None
    # For endpoints whose rows reference other resources only inside JSON:API `relationships`
    # (e.g. `/events` rows carry no `id` of their own): relationship name -> column name under
    # which the related resource's id is promoted to the row root.
    relationship_id_fields: Optional[dict[str, str]] = None
    # Human-readable note surfaced in the schema picker / docs.
    description: Optional[str] = None


NORTHPASS_ENDPOINTS: dict[str, NorthpassEndpointConfig] = {
    "people": NorthpassEndpointConfig(
        name="people",
        path="/people",
        partition_key="created_at",
    ),
    "courses": NorthpassEndpointConfig(
        name="courses",
        path="/courses",
        partition_key="created_at",
    ),
    "learning_paths": NorthpassEndpointConfig(
        name="learning_paths",
        path="/learning-paths",
        partition_key="created_at",
    ),
    "categories": NorthpassEndpointConfig(
        name="categories",
        path="/categories",
        partition_key="created_at",
    ),
    "groups": NorthpassEndpointConfig(
        name="groups",
        path="/groups",
        partition_key="created_at",
    ),
    "quizzes": NorthpassEndpointConfig(
        name="quizzes",
        path="/quizzes",
        partition_key="created_at",
    ),
    # Enrollments have no top-level list endpoint — they're only reachable per course / learning
    # path, so these fan out over the parent resource. The parent id is injected into each row and
    # forms part of the primary key (the enrollment id is only documented as unique per parent).
    "course_enrollments": NorthpassEndpointConfig(
        name="course_enrollments",
        path="/courses/{parent_id}/enrollments",
        partition_key="enrolled_at",
        primary_keys=["course_id", "id"],
        fan_out_parent="courses",
        parent_id_field="course_id",
        description="Enrollments for every course. Fans out one request per course. Full refresh only.",
    ),
    "learning_path_enrollments": NorthpassEndpointConfig(
        name="learning_path_enrollments",
        path="/learning-paths/{parent_id}/enrollments",
        partition_key="enrolled_at",
        primary_keys=["learning_path_id", "id"],
        fan_out_parent="learning_paths",
        parent_id_field="learning_path_id",
        description="Enrollments for every learning path. Fans out one request per learning path. Full refresh only.",
    ),
    # Lesson-level progress. `course_activities` is the per-course lesson catalog (the API exposes
    # no timestamps on activities, so no partitioning), and `activity_events` is the learning-event
    # stream recording who did what on which activity when.
    "course_activities": NorthpassEndpointConfig(
        name="course_activities",
        path="/courses/{parent_id}/activities",
        primary_keys=["course_id", "id"],
        fan_out_parent="courses",
        parent_id_field="course_id",
        description="Activities (lessons) that make up every course. Fans out one request per course. Full refresh only.",
    ),
    "activity_events": NorthpassEndpointConfig(
        name="activity_events",
        path="/events",
        partition_key="created_at",
        # Events carry no id of their own; a row is identified by who did what on which activity
        # when. Same-second duplicates collapse, acceptable for a full-refresh-only table.
        primary_keys=["person_id", "activity_id", "type", "created_at"],
        # The endpoint has no server-side filter, so every sync re-fetches the full event history —
        # potentially very large, so users opt in per schema.
        should_sync_default=False,
        relationship_id_fields={"person": "person_id", "activity": "activity_id"},
        description="Lesson-level learning events (e.g. learner viewed an activity), one row per person, activity, and timestamp. Re-syncs the full history on every run, so it is off by default.",
    ),
}

ENDPOINTS = tuple(NORTHPASS_ENDPOINTS.keys())

# Northpass documents no server-side timestamp filter, so no endpoint advertises incremental fields.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in NORTHPASS_ENDPOINTS}
