from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField


@frozen
class GitBookEndpointConfig:
    name: str
    # Path relative to the API base URL. Fan-out endpoints carry a single `{parent_id}`
    # placeholder resolved per parent organization or space.
    path: str
    # Fan-out parent resource. Organizations come straight from `/orgs`; spaces, sites and teams
    # are enumerated per organization via `/orgs/{id}/<parent>`. Site- and team-scoped paths also
    # carry an `{organization_id}` placeholder, bound from the parent row.
    parent: Optional[Literal["organization", "space", "site", "team"]] = None
    # When set, the parent's id is injected into every row under this column so rows from
    # different parents stay distinguishable (and usable in composite primary keys). Site- and
    # team-scoped rows also get `organization_id`.
    parent_id_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # False for endpoints that return their whole collection in one response and take no `limit`.
    paginated: bool = True
    data_selector: str = "items"
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Query param that filters rows server-side to at or after the incremental watermark.
    incremental_param: Optional[str] = None
    sort_mode: Literal["asc", "desc"] = "asc"


# GitBook REST API v1 list endpoints (https://gitbook.com/docs/developers). All are full refresh
# except `site_answers`: per the published OpenAPI spec, it is the only list endpoint whose
# timestamp filter (`from`) restricts the rows returned. `site_questions` also takes `from`, but
# there it only narrows the embedded stats, not which questions are listed.
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
    # The page tree of each space's current revision, flattened to one row per page. The endpoint
    # returns the whole tree in one `{"pages": [...]}` response with no pagination. Page ids are
    # only documented as unique within a revision, so they pair with the space id.
    "pages": GitBookEndpointConfig(
        name="pages",
        path="/spaces/{parent_id}/content/pages",
        parent="space",
        parent_id_key="space_id",
        primary_keys=["space_id", "id"],
        paginated=False,
        data_selector="pages",
    ),
    "site_questions": GitBookEndpointConfig(
        name="site_questions",
        path="/orgs/{organization_id}/sites/{parent_id}/questions",
        parent="site",
        parent_id_key="site_id",
        primary_keys=["organization_id", "site_id", "id"],
        partition_key="createdAt",
    ),
    # The API does not document the order of answers, and rows arrive grouped per site, so
    # `sort_mode="desc"` makes the pipeline persist the watermark only when a sync completes.
    # `from` is inclusive, so the boundary row is re-pulled and the merge dedupes it.
    "site_answers": GitBookEndpointConfig(
        name="site_answers",
        path="/orgs/{organization_id}/sites/{parent_id}/answers",
        parent="site",
        parent_id_key="site_id",
        primary_keys=["organization_id", "site_id", "id"],
        partition_key="createdAt",
        incremental_fields=[incremental_field("createdAt")],
        incremental_param="from",
        sort_mode="desc",
    ),
    # Team membership rows nest the user under `organization.user`; its id is lifted to a top-level
    # `user_id` column so it can key the table.
    "team_members": GitBookEndpointConfig(
        name="team_members",
        path="/orgs/{organization_id}/teams/{parent_id}/members",
        parent="team",
        parent_id_key="team_id",
        primary_keys=["organization_id", "team_id", "user_id"],
    ),
}

ENDPOINTS = tuple(GITBOOK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GITBOOK_ENDPOINTS.items() if config.incremental_fields
}
