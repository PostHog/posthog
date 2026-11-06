from dataclasses import field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, frozen

PEOPLE_PAGE_SIZE = 100


@frozen
class CirclebackEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    params: dict[str, Any] = field(default_factory=dict)
    status_passes: tuple[str, ...] = ()
    partition_key: Optional[str] = None
    excluded_fields: tuple[str, ...] = ()
    capture: bool = True
    fanout: Optional[DependentEndpointConfig] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    page_size: int = 0


MEETINGS_PARAMS: dict[str, Any] = {"ownership": "All"}

CIRCLEBACK_ENDPOINTS: dict[str, CirclebackEndpointConfig] = {
    "meetings": CirclebackEndpointConfig(
        name="meetings",
        path="/meetings",
        primary_keys=["id"],
        params=MEETINGS_PARAMS,
        partition_key="createdAt",
        excluded_fields=("privateNotes",),
        capture=False,
    ),
    "transcripts": CirclebackEndpointConfig(
        name="transcripts",
        path="/meeting/{meeting_id}/transcript",
        primary_keys=["meeting_id", "timestamp"],
        capture=False,
        fanout=DependentEndpointConfig(
            parent_name="meetings",
            resolve_param="meeting_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "meeting_id"},
            parent_params=MEETINGS_PARAMS,
            child_response_actions=[
                {"status_code": 403, "action": "ignore"},
                {"status_code": 404, "action": "ignore"},
            ],
        ),
    ),
    "action_items": CirclebackEndpointConfig(
        name="action_items",
        path="/action-items",
        primary_keys=["id"],
        params={"assigneeType": "Anyone"},
        status_passes=("PENDING", "DONE"),
        capture=False,
    ),
    "people": CirclebackEndpointConfig(
        name="people",
        path="/people",
        primary_keys=["id"],
        params={"limit": PEOPLE_PAGE_SIZE},
    ),
    "companies": CirclebackEndpointConfig(
        name="companies",
        path="/companies",
        primary_keys=["domain"],
    ),
    "tags": CirclebackEndpointConfig(
        name="tags",
        path="/tag",
        primary_keys=["id"],
    ),
}

ENDPOINTS = tuple(CIRCLEBACK_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CIRCLEBACK_ENDPOINTS.items()
}
