from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
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
    # the change `updated` timestamp); every other endpoint is full refresh.
    supports_incremental: bool = False
    sort_mode: Literal["asc", "desc"] = "asc"


# The query matching every change regardless of state: Gerrit defaults `/changes/` to
# `status:open`, silently hiding merged/abandoned changes, and `status:closed` covers both
# merged and abandoned.
CHANGES_BASE_QUERY = "status:open OR status:closed"

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
}
