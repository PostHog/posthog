from dataclasses import dataclass
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

DEFAULT_FILLOUT_API_BASE_URL = "https://api.fillout.com/v1/api"
ALLOWED_FILLOUT_API_BASE_URLS = (
    DEFAULT_FILLOUT_API_BASE_URL,
    "https://eu-api.fillout.com/v1/api",
)

# Fillout's `/forms/{formId}/submissions` endpoint caps `limit` at 150.
SUBMISSIONS_PAGE_SIZE = 150

SUBMISSION_TIME_INCREMENTAL: IncrementalField = {
    "label": "submissionTime",
    "type": IncrementalFieldType.DateTime,
    "field": "submissionTime",
    "field_type": IncrementalFieldType.DateTime,
}


@dataclass
class FilloutEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: str | None = None
    partition_key: str | None = None
    page_size: int = SUBMISSIONS_PAGE_SIZE
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_key: str | list[str] = "id"
    fanout: DependentEndpointConfig | None = None


FILLOUT_ENDPOINTS: dict[str, FilloutEndpointConfig] = {
    "forms": FilloutEndpointConfig(
        name="forms",
        path="/forms",
        # `/forms` only returns `formId` and `name` — no timestamp to filter on, so full refresh.
        incremental_fields=[],
        partition_key=None,
        primary_key="formId",
        page_size=SUBMISSIONS_PAGE_SIZE,
        sort_mode="asc",
    ),
    "submissions": FilloutEndpointConfig(
        name="submissions",
        path="/forms/{form_id}/submissions",
        incremental_fields=[SUBMISSION_TIME_INCREMENTAL],
        default_incremental_field="submissionTime",
        # `submissionTime` never changes once a submission is finished, so it is a stable
        # partition key (unlike `lastUpdatedAt`, which moves when a submission is edited).
        partition_key="submissionTime",
        # Fillout only documents `submissionId` as unique within a single form, and this
        # table aggregates submissions across every form, so the parent form id is part of
        # the key to keep it unique table-wide.
        primary_key=["form_id", "submissionId"],
        page_size=SUBMISSIONS_PAGE_SIZE,
        # We request `sort=asc`, so rows arrive oldest-first and the pipeline's ascending
        # incremental watermark bookkeeping is correct.
        sort_mode="asc",
        fanout=DependentEndpointConfig(
            parent_name="forms",
            resolve_param="form_id",
            resolve_field="formId",
            include_from_parent=["formId"],
            parent_field_renames={"formId": "form_id"},
        ),
    ),
}

ENDPOINTS = tuple(FILLOUT_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FILLOUT_ENDPOINTS.items()
}
