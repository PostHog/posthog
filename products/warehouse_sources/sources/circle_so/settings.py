from dataclasses import field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    frozen,
)

API_VERSION = "v2"
BASE_URL = f"https://app.circle.so/api/admin/{API_VERSION}"

# `per_page` caps at 100 on every Admin API v2 list endpoint. Requests count toward a monthly plan
# quota, so always ask for the largest page.
PER_PAGE = 100


@frozen
class CircleSoEndpointConfig:
    name: str
    path: str
    params: dict[str, Any] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # A field that is set once when the record is created. `None` leaves the table unpartitioned.
    partition_key: Optional[str] = "created_at"
    fanout: Optional[DependentEndpointConfig] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    page_size: int = PER_PAGE


def _fanout(parent_name: str, resolve_param: str) -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name=parent_name,
        resolve_param=resolve_param,
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": resolve_param},
        # A parent deleted between the parent listing and its child fetch returns 404. Skip it.
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    )


_CREATED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    }
]

# Sort params give each paged list a stable order, so a record created during a sync does not
# move other records across a page boundary.
_ENDPOINT_LIST: tuple[CircleSoEndpointConfig, ...] = (
    # Without `status=all` the API returns only members who finished their profile setup.
    CircleSoEndpointConfig(name="community_members", path="/community_members", params={"status": "all"}),
    CircleSoEndpointConfig(name="member_tags", path="/member_tags", params={"sort": "oldest"}),
    CircleSoEndpointConfig(name="tagged_members", path="/tagged_members"),
    # Spaces have no creation timestamp.
    CircleSoEndpointConfig(name="spaces", path="/spaces", params={"sort": "oldest"}, partition_key=None),
    CircleSoEndpointConfig(
        name="space_members",
        path="/space_members?space_id={space_id}",
        params={"status": "all"},
        primary_keys=["space_id", "id"],
        fanout=_fanout("spaces", "space_id"),
    ),
    CircleSoEndpointConfig(name="space_groups", path="/space_groups"),
    CircleSoEndpointConfig(
        name="space_group_members",
        path="/space_group_members?space_group_id={space_group_id}",
        params={"status": "all"},
        primary_keys=["space_group_id", "id"],
        fanout=_fanout("space_groups", "space_group_id"),
    ),
    # Without `status=all` the API returns only published posts.
    CircleSoEndpointConfig(name="posts", path="/posts", params={"status": "all", "sort": "oldest"}),
    CircleSoEndpointConfig(name="comments", path="/comments"),
    CircleSoEndpointConfig(name="topics", path="/topics", params={"sort": "oldest"}),
    CircleSoEndpointConfig(name="events", path="/events", params={"sort": "oldest"}),
    # An attendee only carries `rsvp_date`, which changes when the member RSVPs again.
    CircleSoEndpointConfig(
        name="event_attendees",
        path="/event_attendees?event_id={event_id}",
        primary_keys=["event_id", "id"],
        partition_key=None,
        fanout=_fanout("events", "event_id"),
    ),
    CircleSoEndpointConfig(name="course_sections", path="/course_sections", params={"sort": "oldest"}),
    CircleSoEndpointConfig(name="course_lessons", path="/course_lessons", params={"sort": "oldest"}),
    # Without `status=all` the API returns only active access groups.
    CircleSoEndpointConfig(name="access_groups", path="/access_groups", params={"status": "all"}),
    CircleSoEndpointConfig(name="invitation_links", path="/invitation_links"),
    CircleSoEndpointConfig(name="community_segments", path="/community_segments"),
    # Forms have no creation timestamp.
    CircleSoEndpointConfig(name="forms", path="/forms", partition_key=None),
    CircleSoEndpointConfig(
        name="form_submissions",
        path="/forms/{form_id}/submissions",
        primary_keys=["form_id", "id"],
        fanout=_fanout("forms", "form_id"),
    ),
    CircleSoEndpointConfig(name="paywalls", path="/paywalls/search", params={"sort": "created_at", "direction": "asc"}),
    CircleSoEndpointConfig(
        name="community_member_subscriptions",
        path="/community_member_subscriptions",
        params={"sort": "created_at", "direction": "asc"},
    ),
    # The only list endpoint with a server-side filter on a record timestamp (`created_at_gte`).
    CircleSoEndpointConfig(
        name="community_member_charges",
        path="/community_member_charges",
        params={"sort": "created_at", "direction": "asc"},
        incremental_fields=_CREATED_AT_INCREMENTAL,
        default_incremental_field="created_at",
    ),
)

CIRCLE_SO_ENDPOINTS: dict[str, CircleSoEndpointConfig] = {config.name: config for config in _ENDPOINT_LIST}

ENDPOINTS = tuple(CIRCLE_SO_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CIRCLE_SO_ENDPOINTS.items() if config.incremental_fields
}
