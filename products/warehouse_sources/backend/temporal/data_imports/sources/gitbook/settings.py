from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class GitBookEndpointConfig:
    name: str
    # Path relative to the API base URL. Fan-out endpoints carry a single `{parent_id}`
    # placeholder resolved per parent organization or space.
    path: str
    # Fan-out parent resource. Organizations come straight from `/orgs`; spaces are
    # enumerated per organization via `/orgs/{id}/spaces`.
    parent: Optional[Literal["organization", "space"]] = None
    # When set, the parent's id is injected into every row under this column so rows from
    # different parents stay distinguishable (and usable in composite primary keys).
    parent_id_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# GitBook REST API v1 list endpoints (https://gitbook.com/docs/developers). All are full refresh
# only: per the published OpenAPI spec, no list endpoint accepts an updated-after/since timestamp
# filter, so there is no server-side cursor to advance an incremental sync (see the
# implementing-warehouse-sources skill).
#
# Primary keys: space and collection ids are globally addressable (`/spaces/{id}`,
# `/collections/{id}`), so `id` alone is safe there. Member ids are user ids (the same user can
# belong to several organizations) and the uniqueness scope of site/team ids is undocumented, so
# those use a composite key with the injected parent id. Change request `id` scope is also
# undocumented (`number` is explicitly per space), so it pairs with the row's own `space` field.
GITBOOK_ENDPOINTS: dict[str, GitBookEndpointConfig] = {
    "organizations": GitBookEndpointConfig(name="organizations", path="/orgs"),
    "spaces": GitBookEndpointConfig(name="spaces", path="/orgs/{parent_id}/spaces", parent="organization"),
    "collections": GitBookEndpointConfig(
        name="collections", path="/orgs/{parent_id}/collections", parent="organization"
    ),
    "sites": GitBookEndpointConfig(
        name="sites",
        path="/orgs/{parent_id}/sites",
        parent="organization",
        parent_id_key="organization_id",
        primary_keys=["organization_id", "id"],
    ),
    "members": GitBookEndpointConfig(
        name="members",
        path="/orgs/{parent_id}/members",
        parent="organization",
        parent_id_key="organization_id",
        primary_keys=["organization_id", "id"],
    ),
    "teams": GitBookEndpointConfig(
        name="teams",
        path="/orgs/{parent_id}/teams",
        parent="organization",
        parent_id_key="organization_id",
        primary_keys=["organization_id", "id"],
    ),
    "change_requests": GitBookEndpointConfig(
        name="change_requests",
        path="/orgs/{parent_id}/change-requests",
        parent="organization",
        parent_id_key="organization_id",
        primary_keys=["space", "id"],
    ),
    "comments": GitBookEndpointConfig(
        name="comments",
        path="/spaces/{parent_id}/comments",
        parent="space",
        parent_id_key="space_id",
        primary_keys=["space_id", "id"],
    ),
}

ENDPOINTS = tuple(GITBOOK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
