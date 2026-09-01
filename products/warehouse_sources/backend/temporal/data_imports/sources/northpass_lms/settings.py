from dataclasses import dataclass, field
from typing import Any, Optional

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
    # Query params for the collection request; None means the default page-size param. Fan-out
    # child requests always use the default.
    params: Optional[dict[str, Any]] = None
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


# The v2 API has no endpoint that lists quiz attempts, and no resource (quizzes, people,
# enrollments, activities) references them. The only documented place attempt UUIDs and results
# appear is the quiz-completed event stream in the sent-webhooks log (`GET /v2/webhooks`), which
# requires a webhook endpoint subscribed to these events and retains three months of messages.
QUIZ_COMPLETED_EVENT_TYPE = "quiz_completed_events"
# `/webhooks` documents a maximum page size of 50, unlike the other list endpoints.
WEBHOOKS_PAGE_SIZE = 50

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
        # Events carry no id of their own; the (person, activity, type, time) grain is the closest
        # stable key. Full-refresh writes never dedupe on primary keys, so exact duplicates land
        # as-is (harmless for an event stream).
        primary_keys=["person_id", "activity_id", "type", "created_at"],
        # The endpoint has no server-side filter, so every sync re-fetches the full event history —
        # potentially very large, so users opt in per schema.
        should_sync_default=False,
        relationship_id_fields={"person": "person_id", "activity": "activity_id"},
        description="Lesson-level learning events (e.g. learner viewed an activity), one row per person, activity, and timestamp. Re-syncs the full history on every run, so it is off by default.",
    ),
    # Quiz attempts & answers. `quiz_attempts` rows are reshaped from the quiz-completed events in
    # the sent-webhooks log (see `_make_quiz_attempt_flattener`), and `quiz_attempt_answers` fans
    # out over those attempts for per-question answers. Both are off by default: the log only
    # covers accounts with a quiz-completed webhook subscription and its trailing three months, and
    # the answers fan-out costs one request per attempt on every sync.
    "quiz_attempts": NorthpassEndpointConfig(
        name="quiz_attempts",
        path="/webhooks",
        params={"filter[type][in]": QUIZ_COMPLETED_EVENT_TYPE, "limit": WEBHOOKS_PAGE_SIZE},
        partition_key="created_at",
        should_sync_default=False,
        description=(
            "Completed quiz attempts with score and passing threshold, one row per attempt. Built from "
            "quiz-completed events in the sent-webhooks log, which requires a webhook subscribed to "
            "those events and keeps three months of history, so the table is off by default. Full "
            "refresh only."
        ),
    ),
    "quiz_attempt_answers": NorthpassEndpointConfig(
        name="quiz_attempt_answers",
        path="/quiz_attempts/{parent_id}/answers",
        partition_key="created_at",
        primary_keys=["quiz_attempt_id", "id"],
        fan_out_parent="quiz_attempts",
        parent_id_field="quiz_attempt_id",
        should_sync_default=False,
        description=(
            "Per-question learner answers for every completed quiz attempt. Fans out one request per "
            "attempt found in the sent-webhooks log (same coverage caveats as quiz_attempts), so the "
            "table is off by default. Full refresh only."
        ),
    ),
}

ENDPOINTS = tuple(NORTHPASS_ENDPOINTS.keys())

# Northpass documents no server-side timestamp filter, so no endpoint advertises incremental fields.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in NORTHPASS_ENDPOINTS}
