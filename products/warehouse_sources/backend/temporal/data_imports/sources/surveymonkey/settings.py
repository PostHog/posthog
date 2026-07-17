from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# SurveyMonkey caps `per_page` per endpoint (responses/bulk maxes out at 100). We use a
# single conservative value everywhere to avoid 400s, since daily call quotas are low and
# the docs disagree on per-endpoint maxima.
DEFAULT_PAGE_SIZE = 100


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class SurveyMonkeyEndpointConfig:
    name: str
    # Path for top-level endpoints, or a `{survey_id}` template for fan-out endpoints.
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Fan-out endpoints first enumerate every survey, then page the child resource per survey.
    is_fanout: bool = False
    # `survey_questions` has no first-class list endpoint; questions are extracted from the
    # nested pages[].questions[] of `/surveys/{id}/details` (avoids a 2-level fan-out).
    extract_questions_from_details: bool = False
    default_incremental_field: Optional[str] = None
    # Partition on a STABLE field (date_created), never date_modified.
    partition_key: Optional[str] = None
    page_size: int = DEFAULT_PAGE_SIZE
    primary_key: str = "id"
    # The `sort_by` value to request when paging incrementally (must be a server-side enum).
    sort_by: Optional[str] = None


SURVEYMONKEY_ENDPOINTS: dict[str, SurveyMonkeyEndpointConfig] = {
    "surveys": SurveyMonkeyEndpointConfig(
        name="surveys",
        path="/surveys",
        partition_key="date_created",
        default_incremental_field="date_modified",
        # `/surveys` only sorts by date_modified (the sort_by enum is title/date_modified/
        # num_responses) and only exposes a server-side start_modified_at filter, so
        # date_modified is the only viable cursor.
        sort_by="date_modified",
        incremental_fields=[
            _datetime_incremental_field("date_modified"),
        ],
    ),
    "survey_responses": SurveyMonkeyEndpointConfig(
        name="survey_responses",
        path="/surveys/{survey_id}/responses/bulk",
        is_fanout=True,
        partition_key="date_created",
        default_incremental_field="date_modified",
        # responses/bulk exposes both start_modified_at and start_created_at server-side
        # filters, so either timestamp works as a cursor.
        incremental_fields=[
            _datetime_incremental_field("date_modified"),
            _datetime_incremental_field("date_created"),
        ],
    ),
    "survey_pages": SurveyMonkeyEndpointConfig(
        name="survey_pages",
        path="/surveys/{survey_id}/pages",
        is_fanout=True,
    ),
    "survey_questions": SurveyMonkeyEndpointConfig(
        name="survey_questions",
        path="/surveys/{survey_id}/details",
        is_fanout=True,
        extract_questions_from_details=True,
    ),
    "collectors": SurveyMonkeyEndpointConfig(
        name="collectors",
        path="/surveys/{survey_id}/collectors",
        is_fanout=True,
        # The collectors list returns only id/name/href by default, so there is no stable
        # date field to partition on — full refresh, unpartitioned.
    ),
}

ENDPOINTS = tuple(SURVEYMONKEY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SURVEYMONKEY_ENDPOINTS.items()
}

# Datacenter -> API base URL. SurveyMonkey hosts regional datacenters; the correct host is
# returned as `access_url` during the OAuth token exchange, but private-app users know theirs.
DATA_CENTER_BASE_URLS: dict[str, str] = {
    "us": "https://api.surveymonkey.com/v3",
    "eu": "https://api.eu.surveymonkey.com/v3",
    "ca": "https://api.surveymonkey.ca/v3",
}
DEFAULT_DATA_CENTER = "us"
