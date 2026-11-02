from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class GerritFanoutConfig:
    # Child path; `{key}` is replaced with the parent row's `key_field` value.
    path: str
    key_field: str
    # Change and group ids arrive URL-encoded from their list endpoints; project names don't.
    quote_key: bool = False
    # "list" returns a JSON array; "map_of_lists" returns an object keyed by `map_key_column`
    # whose values are arrays (e.g. comments keyed by file path).
    response_kind: Literal["list", "map_of_lists"] = "list"
    map_key_column: str = "path"
    # Parents that disappear or can't serve the child between the list and the child request.
    ignore_statuses: frozenset[int] = frozenset({404})


@dataclass(frozen=False)
class GerritEndpointConfig:
    name: str
    path: str
    # Gerrit signals "there are more results" with a boolean flag on the last entry of a
    # truncated page (e.g. `_more_changes`) instead of a next-page token.
    more_flag: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # "list" endpoints return a JSON array; "map" endpoints (/projects/, /groups/) return an
    # object keyed by resource name, with the name omitted from some entries.
    response_kind: Literal["list", "map"] = "list"
    # Static query params sent on every request. Values that are lists are repeated
    # (e.g. the `o` option params on /changes/).
    params: dict[str, str | list[str]] = field(default_factory=dict)
    page_size: int = 100
    # Stable creation-time field used for datetime partitioning. Only changes carry one in
    # their list payload.
    partition_key: Optional[str] = None
    # Only /changes/ exposes a server-side timestamp filter (the `after:` query operator on
    # the change `updated` timestamp); endpoints listing anything else are full refresh.
    supports_incremental: bool = False
    sort_mode: Literal["asc", "desc"] = "asc"
    # When set, the endpoint's own listing is the parent and each row is fetched per parent.
    fanout: Optional[GerritFanoutConfig] = None
    # Emit one row per file of each change's current revision instead of the change itself.
    expand_current_files: bool = False
    # Parent fields copied onto each derived row (fan-out children and expanded files), as
    # parent field -> row column.
    include_from_parent: dict[str, str] = field(default_factory=dict)


# The query matching every change regardless of state: Gerrit defaults `/changes/` to
# `status:open`, silently hiding merged/abandoned changes, and `status:closed` covers both
# merged and abandoned.
CHANGES_BASE_QUERY = "status:open OR status:closed"

# `_change_number` follows Gerrit's own naming for a change reference (e.g. RelatedChangeAndCommitInfo).
CHANGE_PARENT_FIELDS = {
    "_number": "_change_number",
    "project": "project",
    "updated": "change_updated",
    "created": "change_created",
}

GERRIT_ENDPOINTS: dict[str, GerritEndpointConfig] = {
    "changes": GerritEndpointConfig(
        name="changes",
        path="/changes/",
        more_flag="_more_changes",
        primary_keys=["id"],
        params={
            # CURRENT_REVISION (not ALL_REVISIONS) keeps row size bounded on long-lived
            # changes with hundreds of patch sets; MESSAGES carries the full review timeline.
            "o": ["DETAILED_LABELS", "CURRENT_REVISION", "MESSAGES", "DETAILED_ACCOUNTS"],
        },
        partition_key="created",
        supports_incremental=True,
        # Gerrit returns changes newest-first on `updated` and offers no ascending sort.
        sort_mode="desc",
    ),
    "accounts": GerritEndpointConfig(
        name="accounts",
        path="/accounts/",
        more_flag="_more_accounts",
        primary_keys=["_account_id"],
        # /accounts/ requires a query; `is:active` lists every active account.
        params={"q": "is:active", "o": ["DETAILS"]},
    ),
    "projects": GerritEndpointConfig(
        name="projects",
        path="/projects/",
        more_flag="_more_projects",
        primary_keys=["id"],
        response_kind="map",
        # `d` includes project descriptions in the listing.
        params={"d": ""},
    ),
    "groups": GerritEndpointConfig(
        name="groups",
        path="/groups/",
        more_flag="_more_groups",
        primary_keys=["id"],
        response_kind="map",
    ),
    "group_members": GerritEndpointConfig(
        name="group_members",
        path="/groups/",
        more_flag="_more_groups",
        # `group_uuid` rather than `group_id`: GroupInfo already uses `group_id` for the numeric id.
        primary_keys=["group_uuid", "_account_id"],
        response_kind="map",
        fanout=GerritFanoutConfig(
            path="/groups/{key}/members/",
            key_field="id",
            # External groups (LDAP, system groups) have no member list and answer 405.
            ignore_statuses=frozenset({404, 405}),
        ),
        include_from_parent={"id": "group_uuid"},
    ),
    "project_branches": GerritEndpointConfig(
        name="project_branches",
        path="/projects/",
        more_flag="_more_projects",
        primary_keys=["project", "ref"],
        response_kind="map",
        fanout=GerritFanoutConfig(path="/projects/{key}/branches/", key_field="name", quote_key=True),
        include_from_parent={"name": "project"},
    ),
    "change_comments": GerritEndpointConfig(
        name="change_comments",
        path="/changes/",
        more_flag="_more_changes",
        # Comment ids are only documented as unique within a change.
        primary_keys=["_change_number", "id"],
        fanout=GerritFanoutConfig(
            path="/changes/{key}/comments",
            key_field="id",
            response_kind="map_of_lists",
        ),
        include_from_parent=CHANGE_PARENT_FIELDS,
        partition_key="change_created",
        # A new comment bumps the change's `updated`, so the parent filter picks up every
        # change with new comments.
        supports_incremental=True,
        sort_mode="desc",
    ),
    "change_files": GerritEndpointConfig(
        name="change_files",
        path="/changes/",
        more_flag="_more_changes",
        primary_keys=["_change_number", "revision", "path"],
        # CURRENT_FILES inlines the per-file diffstat into the listing, so no per-change request.
        params={"o": ["CURRENT_REVISION", "CURRENT_FILES"]},
        expand_current_files=True,
        include_from_parent=CHANGE_PARENT_FIELDS,
        partition_key="change_created",
        supports_incremental=True,
        sort_mode="desc",
    ),
}

ENDPOINTS = tuple(GERRIT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "changes": [
        {
            "label": "updated",
            "type": IncrementalFieldType.DateTime,
            "field": "updated",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    **{
        endpoint: [
            {
                "label": "change_updated",
                "type": IncrementalFieldType.DateTime,
                "field": "change_updated",
                "field_type": IncrementalFieldType.DateTime,
            },
        ]
        for endpoint in ("change_comments", "change_files")
    },
}
