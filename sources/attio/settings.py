from dataclasses import dataclass
from typing import Literal


@dataclass
class AttioEndpointConfig:
    name: str
    path: str
    primary_key: str = "record_id"
    partition_key: str = "created_at"
    method: Literal["GET", "POST"] = "GET"
    page_size: int = 500


# Attio API doesn't support updatedAt filtering, so only full refresh is supported
ATTIO_ENDPOINTS: dict[str, AttioEndpointConfig] = {
    "companies": AttioEndpointConfig(
        name="companies",
        path="/v2/objects/companies/records/query",
        method="POST",
        primary_key="record_id",
    ),
    "people": AttioEndpointConfig(
        name="people",
        path="/v2/objects/people/records/query",
        method="POST",
        primary_key="record_id",
    ),
    "deals": AttioEndpointConfig(
        name="deals",
        path="/v2/objects/deals/records/query",
        method="POST",
        primary_key="record_id",
    ),
    "users": AttioEndpointConfig(
        name="users",
        path="/v2/objects/users/records/query",
        method="POST",
        primary_key="record_id",
    ),
    "workspaces": AttioEndpointConfig(
        name="workspaces",
        path="/v2/objects/workspaces/records/query",
        method="POST",
        primary_key="record_id",
    ),
    "lists": AttioEndpointConfig(
        name="lists",
        path="/v2/lists",
        method="GET",
        primary_key="list_id",
    ),
    "notes": AttioEndpointConfig(
        name="notes",
        path="/v2/notes",
        method="GET",
        primary_key="note_id",
        page_size=50,
    ),
    "tasks": AttioEndpointConfig(
        name="tasks",
        path="/v2/tasks",
        method="GET",
        primary_key="task_id",
    ),
    "workspace_members": AttioEndpointConfig(
        name="workspace_members",
        path="/v2/workspace_members",
        method="GET",
        primary_key="workspace_member_id",
    ),
}

ENDPOINTS = tuple(ATTIO_ENDPOINTS.keys())
