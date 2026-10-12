from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class TeamworkEndpointConfig:
    name: str
    # V3 list-endpoint path, relative to https://{site}.teamwork.com/projects/api/v3
    path: str
    # Top-level key in the response envelope holding the array of records (e.g. {"projects": [...]}).
    data_key: str
    # `orderBy` value passed to the API. Rows are always requested with `orderMode=asc`.
    # For incremental endpoints this MUST be the server's update-time sort so the cursor watermark
    # advances monotonically; for full-refresh endpoints it's a stable created/added sort that keeps
    # pagination from skipping/duplicating rows as data changes mid-sync. None = don't send `orderBy`.
    order_by: Optional[str] = None
    # Record field the incremental cursor reads (and what `updatedAfter` filters on server-side).
    # None means the endpoint has no usable server-side update sort, so it's full refresh only.
    incremental_field: Optional[str] = None
    # Stable datetime field to partition by (a creation timestamp — never an update timestamp, which
    # would rewrite partitions every sync). None = no partitioning.
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


def _incremental(field_name: str) -> list[IncrementalField]:
    return [
        {
            "label": field_name,
            "type": IncrementalFieldType.DateTime,
            "field": field_name,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


# Teamwork.com Projects V3 endpoints. Paths, response keys, and the per-endpoint `orderBy` enum were
# taken from the public V3 API docs (https://apidocs.teamwork.com). Incremental sync is enabled only
# where the docs confirm BOTH a server-side `updatedAfter` filter AND an ascending sort by the update
# field; everything else ships full refresh. The exact record field names (`dateUpdated`, `dateEdited`,
# `dateCreated`) follow the documented `fields[...]` projections and per-endpoint `orderBy` casing, but
# could not be curl-verified against a live account — see the PR description.
TEAMWORK_ENDPOINTS: dict[str, TeamworkEndpointConfig] = {
    "projects": TeamworkEndpointConfig(
        name="projects",
        path="/projects.json",
        data_key="projects",
        # `projects` exposes no update-time sort (orderBy: name/datecreated/lastactivity/...), so it
        # can't drive a safe incremental watermark — full refresh, stable-sorted by creation date.
        order_by="datecreated",
    ),
    "tasks": TeamworkEndpointConfig(
        name="tasks",
        path="/tasks.json",
        data_key="tasks",
        order_by="updatedat",
        incremental_field="dateUpdated",
    ),
    "tasklists": TeamworkEndpointConfig(
        name="tasklists",
        path="/tasklists.json",
        data_key="tasklists",
        order_by="updatedat",
        incremental_field="dateUpdated",
    ),
    "milestones": TeamworkEndpointConfig(
        name="milestones",
        path="/milestones.json",
        data_key="milestones",
        order_by="dateUpdated",
        incremental_field="dateUpdated",
        partition_key="dateCreated",
    ),
    "timelogs": TeamworkEndpointConfig(
        name="timelogs",
        path="/time.json",
        data_key="timelogs",
        order_by="dateupdated",
        # V3 timelogs expose the edit timestamp as `dateEdited` (there is no `dateUpdated` field on
        # the record), while the sort enum is `dateupdated`. The cursor reads `dateEdited`.
        incremental_field="dateEdited",
        partition_key="dateCreated",
    ),
    "people": TeamworkEndpointConfig(
        name="people",
        path="/people.json",
        data_key="people",
        # `people` only sorts by name — no update sort — so full refresh.
        order_by="name",
    ),
    "companies": TeamworkEndpointConfig(
        name="companies",
        path="/companies.json",
        data_key="companies",
        # No update sort available; full refresh, stable-sorted by when the company was added.
        order_by="dateadded",
    ),
    "tags": TeamworkEndpointConfig(
        name="tags",
        path="/tags.json",
        data_key="tags",
        order_by="name",
    ),
    "comments": TeamworkEndpointConfig(
        name="comments",
        path="/comments.json",
        data_key="comments",
        # `comments` only sorts by date/project/user/type — no update sort — so full refresh.
        order_by="date",
    ),
}

ENDPOINTS = tuple(TEAMWORK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: _incremental(config.incremental_field)
    for name, config in TEAMWORK_ENDPOINTS.items()
    if config.incremental_field is not None
}
