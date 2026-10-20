from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

TEACHABLE_BASE_URL = "https://developers.teachable.com"

# Teachable documents a 20-row default page size (5 for /pricing_plans). We request more via
# `per`; if the server clamps it, pagination still terminates correctly because the paginators
# stop on `meta.number_of_pages` / `meta.has_more_results` / an empty page, never on the
# requested page size.
DEFAULT_PAGE_SIZE = 100

# Teachable notes new transactions can take up to two minutes to appear via the API, and the
# `start` filter is exclusive of the given instant — re-read a trailing window on each
# incremental sync so late-arriving boundary rows aren't skipped (the merge dedupes on `id`).
TRANSACTIONS_INCREMENTAL_LOOKBACK_SECONDS = 300


@dataclass
class TeachableEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_key: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    partition_key: str | None = None
    page_size: int = DEFAULT_PAGE_SIZE
    fanout: DependentEndpointConfig | None = None


TEACHABLE_ENDPOINTS: dict[str, TeachableEndpointConfig] = {
    "users": TeachableEndpointConfig(
        name="users",
        path="/v1/users",
        data_selector="users",
        primary_key=["id"],
        # The list response only carries id/name/email — no timestamp to filter or partition
        # on, so full refresh with no partitioning.
    ),
    "courses": TeachableEndpointConfig(
        name="courses",
        path="/v1/courses",
        data_selector="courses",
        primary_key=["id"],
        # Course rows have no timestamp field and no server-side change filter — full refresh.
    ),
    "course_enrollments": TeachableEndpointConfig(
        name="course_enrollments",
        path="/v1/courses/{course_id}/enrollments",
        data_selector="enrollments",
        # user_id is only unique within a course, and this table aggregates enrollments across
        # every course, so the parent course id is part of the key to keep it unique table-wide.
        primary_key=["course_id", "user_id"],
        # enrolled_at never changes once a user is enrolled (unlike percent_complete /
        # completed_at, which move as the student progresses).
        partition_key="enrolled_at",
        # Full refresh only: the API does offer a server-side `enrolled_in_after` filter, but
        # enrollment rows mutate (percent_complete, completed_at), so an enrolled_at cursor
        # would freeze progress fields on already-synced rows.
        fanout=DependentEndpointConfig(
            parent_name="courses",
            resolve_param="course_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "course_id"},
        ),
    ),
    "transactions": TeachableEndpointConfig(
        name="transactions",
        path="/v1/transactions",
        data_selector="transactions",
        primary_key=["id"],
        incremental_fields=[incremental_field("created_at")],
        default_incremental_field="created_at",
        partition_key="created_at",
    ),
    "pricing_plans": TeachableEndpointConfig(
        name="pricing_plans",
        path="/v1/pricing_plans",
        data_selector="pricing_plans",
        primary_key=["id"],
        partition_key="created_at",
        # No server-side updated-since filter, so full refresh (the table is small).
    ),
    # The four endpoints below sit two or more levels under /v1/courses, so `teachable.py` walks
    # them with its own iterators. None has a server-side time filter: all are full refresh.
    "course_progress": TeachableEndpointConfig(
        name="course_progress",
        # Needs a `user_id` query param, so this fans out over each course's enrollments.
        path="/v1/courses/{course_id}/progress",
        data_selector="course_progress",
        primary_key=["course_id", "user_id"],
        partition_key="enrolled_at",
    ),
    "lectures": TeachableEndpointConfig(
        name="lectures",
        # There is no lecture list endpoint: lecture ids come from the course detail curriculum.
        path="/v1/courses/{course_id}/lectures/{lecture_id}",
        data_selector="lecture",
        primary_key=["course_id", "id"],
    ),
    "quizzes": TeachableEndpointConfig(
        name="quizzes",
        # The list endpoint returns only `quiz_ids`, so each id is resolved through
        # /quizzes/{quiz_id} to get the quiz name and questions.
        path="/v1/courses/{course_id}/lectures/{lecture_id}/quizzes",
        data_selector="quiz_ids",
        primary_key=["course_id", "lecture_id", "id"],
    ),
    "quiz_responses": TeachableEndpointConfig(
        name="quiz_responses",
        path="/v1/courses/{course_id}/lectures/{lecture_id}/quizzes/{quiz_id}/responses",
        data_selector="responses",
        # The docs don't say whether a retake replaces the earlier submission, so the
        # submission time is part of the key.
        primary_key=["course_id", "lecture_id", "quiz_id", "student_id", "submitted_at"],
        partition_key="submitted_at",
    ),
}

ENDPOINTS = tuple(TEACHABLE_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TEACHABLE_ENDPOINTS.items()
}
