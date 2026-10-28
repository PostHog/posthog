from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.mn.co/admin/v1"

# Mighty Networks caps `per_page` at 100 (default 25). Always request the max to minimise round trips.
PER_PAGE = 100

ENDPOINTS = (
    "Members",
    "Spaces",
    "Posts",
    "Events",
    "Plans",
    "Subscriptions",
    "Purchases",
    "Tags",
    "Badges",
    "SpaceMembers",
    "PlanMembers",
    "MemberTags",
    "MemberBadges",
    "EventRsvps",
)

# Path under /admin/v1/networks/{network_id}.
PATHS: dict[str, str] = {
    "Members": "/members",
    "Spaces": "/spaces",
    "Posts": "/posts",
    "Events": "/events",
    "Plans": "/plans",
    "Subscriptions": "/subscriptions",
    "Purchases": "/purchases",
    "Tags": "/tags",
    "Badges": "/badges",
    "SpaceMembers": "/spaces/{space_id}/members",
    "PlanMembers": "/plans/{plan_id}/members",
    "MemberTags": "/members/{member_id}/tags",
    "MemberBadges": "/members/{member_id}/badges",
    "EventRsvps": "/events/{event_id}/rsvps",
}


def _fanout(parent_name: str, resolve_param: str) -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name=parent_name,
        resolve_param=resolve_param,
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": resolve_param},
        # A parent removed between the parent listing and its child fetch 404s; skip it rather
        # than fail the run with the "network not found" non-retryable error.
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    )


# These lists are only reachable per parent, so each child row carries its parent id.
FANOUTS: dict[str, DependentEndpointConfig] = {
    "SpaceMembers": _fanout("Spaces", "space_id"),
    "PlanMembers": _fanout("Plans", "plan_id"),
    "MemberTags": _fanout("Members", "member_id"),
    "MemberBadges": _fanout("Members", "member_id"),
    "EventRsvps": _fanout("Events", "event_id"),
}


@frozen
class MightyNetworksEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    page_size: int = PER_PAGE


ENDPOINT_CONFIGS: dict[str, MightyNetworksEndpointConfig] = {
    name: MightyNetworksEndpointConfig(name=name, path=PATHS[name], incremental_fields=[]) for name in ENDPOINTS
}

# Subscriptions and Purchases nest the record's real id under a `subscription`/`purchase` object
# rather than exposing it at the row root (see mighty_networks.py's flatten helpers), everything
# else has a flat `id`.
# Fan-out child ids (a member, tag, or badge id) repeat across parents, so the parent id is part
# of the key.
PRIMARY_KEYS: dict[str, list[str]] = {
    name: [FANOUTS[name].resolve_param, "id"] if name in FANOUTS else ["id"] for name in ENDPOINTS
}

# created_at never changes after creation, unlike updated_at. RSVPs only expose `updated`, so they
# aren't partitioned.
PARTITION_FIELDS: dict[str, str] = {name: "created_at" for name in ENDPOINTS if name != "EventRsvps"}

# No list endpoint documents or accepts an updated_since/created_since filter (checked against the
# published OpenAPI spec at api.mn.co/admin/v1/spec.json and docs.mightynetworks.com/admin-api) —
# every endpoint is full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
