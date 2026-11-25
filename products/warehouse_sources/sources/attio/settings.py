from typing import Literal

from products.warehouse_sources.sources.sdk import frozen

FanoutTarget = Literal["lists", "objects"]


@frozen
class AttioEndpointConfig:
    name: str
    path: str
    primary_keys: tuple[str, ...] = ("record_id",)
    partition_key: str | None = "created_at"
    method: Literal["GET", "POST"] = "GET"
    page_size: int = 500
    pagination: Literal["offset", "cursor", "single"] = "offset"
    # "parent": one child read per object or list. "attribute": one child read per attribute of
    # `attribute_type` on each object or list.
    fanout: Literal["parent", "attribute"] | None = None
    fanout_targets: tuple[FanoutTarget, ...] = ("lists", "objects")
    attribute_type: str | None = None
    params: tuple[tuple[str, str], ...] = ()


# Attio API doesn't support updatedAt filtering, so only full refresh is supported
ATTIO_ENDPOINTS: dict[str, AttioEndpointConfig] = {
    "companies": AttioEndpointConfig(
        name="companies",
        path="/v2/objects/companies/records/query",
        method="POST",
    ),
    "people": AttioEndpointConfig(
        name="people",
        path="/v2/objects/people/records/query",
        method="POST",
    ),
    "deals": AttioEndpointConfig(
        name="deals",
        path="/v2/objects/deals/records/query",
        method="POST",
    ),
    "users": AttioEndpointConfig(
        name="users",
        path="/v2/objects/users/records/query",
        method="POST",
    ),
    "workspaces": AttioEndpointConfig(
        name="workspaces",
        path="/v2/objects/workspaces/records/query",
        method="POST",
    ),
    "lists": AttioEndpointConfig(
        name="lists",
        path="/v2/lists",
        method="GET",
        primary_keys=("list_id",),
    ),
    "notes": AttioEndpointConfig(
        name="notes",
        path="/v2/notes",
        method="GET",
        primary_keys=("note_id",),
        page_size=50,
    ),
    "tasks": AttioEndpointConfig(
        name="tasks",
        path="/v2/tasks",
        method="GET",
        primary_keys=("task_id",),
    ),
    "workspace_members": AttioEndpointConfig(
        name="workspace_members",
        path="/v2/workspace_members",
        method="GET",
        primary_keys=("workspace_member_id",),
    ),
    "activities": AttioEndpointConfig(
        name="activities",
        path="/v2/activities",
        method="GET",
        primary_keys=("activity_id",),
        pagination="cursor",
    ),
    "objects": AttioEndpointConfig(
        name="objects",
        path="/v2/objects",
        method="GET",
        primary_keys=("object_id",),
        pagination="single",
    ),
    # Attribute, option and status ids are UUIDs, but the parent object or list id stays in the key
    # because the API only documents them per parent.
    "attributes": AttioEndpointConfig(
        name="attributes",
        path="/v2/{target}/{identifier}/attributes",
        method="GET",
        primary_keys=("object_id", "attribute_id"),
        page_size=100,
        fanout="parent",
        params=(("show_archived", "true"),),
    ),
    "select_options": AttioEndpointConfig(
        name="select_options",
        path="/v2/{target}/{identifier}/attributes/{attribute}/options",
        method="GET",
        primary_keys=("object_id", "attribute_id", "option_id"),
        partition_key=None,
        pagination="single",
        fanout="attribute",
        attribute_type="select",
        params=(("show_archived", "true"),),
    ),
    "statuses": AttioEndpointConfig(
        name="statuses",
        path="/v2/{target}/{identifier}/attributes/{attribute}/statuses",
        method="GET",
        primary_keys=("object_id", "attribute_id", "status_id"),
        partition_key=None,
        pagination="single",
        fanout="attribute",
        attribute_type="status",
        params=(("show_archived", "true"),),
    ),
    "list_entries": AttioEndpointConfig(
        name="list_entries",
        path="/v2/lists/{identifier}/entries/query",
        method="POST",
        primary_keys=("list_id", "entry_id"),
        fanout="parent",
        fanout_targets=("lists",),
    ),
}

ENDPOINTS = tuple(ATTIO_ENDPOINTS.keys())
