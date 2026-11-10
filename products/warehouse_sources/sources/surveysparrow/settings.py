from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, SortMode

# SurveySparrow caps `limit` per endpoint: 100 on surveys/questions/tickets/channels, 200 on
# responses, 50 on contacts, contact_lists and users. Each endpoint config carries its own maximum to minimise round
# trips without 400s.
DEFAULT_PAGE_SIZE = 100

COMPLETED_TIME_INCREMENTAL: IncrementalField = {
    "label": "completed_time",
    "type": IncrementalFieldType.DateTime,
    "field": "completed_time",
    "field_type": IncrementalFieldType.DateTime,
}

UPDATED_AT_INCREMENTAL: IncrementalField = {
    "label": "updated_at",
    "type": IncrementalFieldType.DateTime,
    "field": "updated_at",
    "field_type": IncrementalFieldType.DateTime,
}


@dataclass(frozen=False)
class SurveySparrowEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Fan-out endpoints first enumerate every survey, then page the child resource per survey
    # (SurveySparrow requires `survey_id` as a query param on /v3/responses, /v3/questions and
    # /v3/channels).
    is_fanout: bool = False
    default_incremental_field: Optional[str] = None
    # Server-side filter param the incremental cutoff maps to.
    cutoff_param: Optional[str] = None
    # Whether the filter takes a full `YYYY-MM-DDTHH:MM:SS` timestamp rather than a `YYYY-MM-DD` date.
    cutoff_includes_time: bool = False
    # Only "asc" when the request sorts on the incremental field server-side.
    sort_mode: Optional[SortMode] = None
    # Partition on a STABLE field (created_at / completed_time), never updated_at.
    partition_key: Optional[str] = None
    page_size: int = DEFAULT_PAGE_SIZE
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Static query params sent on every request (e.g. a server-side sort on the cursor field).
    extra_params: dict[str, str] = field(default_factory=dict)


SURVEYSPARROW_ENDPOINTS: dict[str, SurveySparrowEndpointConfig] = {
    # Full refresh: /v3/surveys documents created/updated date filters but no sort param, so
    # neither pagination stability nor watermark ordering can be guaranteed for an incremental
    # cursor. The table is small, so a full refresh per sync is cheap.
    "surveys": SurveySparrowEndpointConfig(
        name="surveys",
        path="/v3/surveys",
        partition_key="created_at",
        page_size=100,
    ),
    "responses": SurveySparrowEndpointConfig(
        name="responses",
        path="/v3/responses",
        is_fanout=True,
        partition_key="completed_time",
        default_incremental_field="completed_time",
        cutoff_param="date.gte",
        incremental_fields=[COMPLETED_TIME_INCREMENTAL],
        page_size=200,
        # A response id is only documented as unique within its survey, and the table
        # aggregates responses across every survey, so the survey id is part of the key.
        primary_keys=["survey_id", "id"],
        # Only completed responses: partial submissions have no `completed_time`, which is both
        # the incremental cursor and the partition key. Sort ascending on the cursor field so
        # the pipeline's watermark advances monotonically and page-number pagination stays
        # stable as new responses arrive.
        extra_params={"state": "completed", "order_by": "completedTime", "order": "ASC"},
        sort_mode="asc",
    ),
    "questions": SurveySparrowEndpointConfig(
        name="questions",
        path="/v3/questions",
        is_fanout=True,
        page_size=100,
        primary_keys=["survey_id", "id"],
    ),
    "contacts": SurveySparrowEndpointConfig(
        name="contacts",
        path="/v3/contacts",
        # The contact endpoints cap `limit` at 50, unlike surveys/questions/responses.
        page_size=50,
    ),
    "contact_lists": SurveySparrowEndpointConfig(
        name="contact_lists",
        path="/v3/contact_lists",
        # /v3/contact_lists caps `limit` at 50, same as /v3/contacts.
        page_size=50,
    ),
    "users": SurveySparrowEndpointConfig(
        name="users",
        path="/v3/users",
        page_size=50,
    ),
    "tickets": SurveySparrowEndpointConfig(
        name="tickets",
        path="/v3/tickets",
        partition_key="created_at",
        default_incremental_field="updated_at",
        cutoff_param="updated_date.gte",
        cutoff_includes_time=True,
        incremental_fields=[UPDATED_AT_INCREMENTAL],
        page_size=100,
        # /v3/tickets documents no sort param, so rows arrive in no known order (sort_mode=None).
    ),
    "channels": SurveySparrowEndpointConfig(
        name="channels",
        path="/v3/channels",
        # /v3/channels requires `survey_id`, so it fans out over every survey like questions.
        is_fanout=True,
        page_size=100,
        primary_keys=["survey_id", "id"],
    ),
}

ENDPOINTS = tuple(SURVEYSPARROW_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SURVEYSPARROW_ENDPOINTS.items()
}

# Data center -> API base URL. SurveySparrow assigns each account to a regional data center;
# tokens are only valid against their own region's host. Every host below responds on
# /v3/surveys (verified by probe), including the Sydney host, which the docs list with an
# `-app` suffix instead of `-api`.
DATA_CENTER_BASE_URLS: dict[str, str] = {
    "us": "https://api.surveysparrow.com",
    "eu": "https://eu-api.surveysparrow.com",
    "ap": "https://ap-api.surveysparrow.com",
    "me": "https://me-api.surveysparrow.com",
    "uk": "https://eu-ln-api.surveysparrow.com",
    "ap-sy": "https://ap-sy-app.surveysparrow.com",
    "ca": "https://ca-api.surveysparrow.com",
}
DEFAULT_DATA_CENTER = "us"
