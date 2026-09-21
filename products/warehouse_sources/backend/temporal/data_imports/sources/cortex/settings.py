from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

# Cortex is a single global SaaS deployment (no regional hosts, no per-tenant subdomain).
CORTEX_BASE_URL = "https://api.getcortexapp.com/api/v1"

# List endpoints default to 250 and cap at 1000 per the API docs.
DEFAULT_PAGE_SIZE = 250


@dataclass(frozen=True)
class CortexEndpointConfig:
    name: str
    path: str
    # jsonpath selector into the response body for the list of rows.
    data_selector: str
    primary_key: list[str]
    # Every top-level list endpoint uses 0-indexed page/pageSize pagination; `teams` returns its
    # full collection in one response with no page/pageSize params documented.
    paginated: bool = True
    # jsonpath to the response's `totalPages` field, used to terminate pagination without an
    # extra trailing empty-page request. Endpoints that don't expose it stop on a short page.
    total_path: str | None = None
    page_size: int = DEFAULT_PAGE_SIZE
    # Stable creation-time field to partition by. Left None for endpoints with no such field
    # (never a mutable field like lastUpdated/lastEvaluated).
    partition_key: str | None = None
    # Only the per-entity custom event stream documents a server-side time filter (`startTime`);
    # every other Cortex list endpoint is full-refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # Rows from a fan-out arrive grouped per parent, so the run only knows its true high-water
    # mark once every parent has been walked. "desc" is what defers the watermark commit to the
    # end of the run; committing per batch would skip history for parents not yet visited.
    sort_mode: SortMode = "asc"
    fanout: DependentEndpointConfig | None = None


def _entity_fanout(resolve_param: str, parent_field_renames: dict[str, str]) -> DependentEndpointConfig:
    """Fan out over the catalog, binding each entity to a per-entity child path.

    Resolves on `tag_encoded` rather than `tag`: Cortex entity tags may contain forward slashes,
    which have to be percent-encoded to address the entity (see `_encode_entity_tag` in cortex.py).
    """
    return DependentEndpointConfig(
        parent_name="entities",
        resolve_param=resolve_param,
        resolve_field="tag_encoded",
        include_from_parent=list(parent_field_renames),
        parent_field_renames=parent_field_renames,
    )


CORTEX_ENDPOINTS: dict[str, CortexEndpointConfig] = {
    "entities": CortexEndpointConfig(
        name="entities",
        path="/catalog",
        data_selector="entities",
        # `id` (the 18-char CID) is globally unique; `tag` is also unique but can be renamed.
        primary_key=["id"],
        total_path="totalPages",
        # No creation-time field is exposed on the list response (only the mutable `lastUpdated`).
    ),
    "scorecards": CortexEndpointConfig(
        name="scorecards",
        path="/scorecards",
        data_selector="scorecards",
        primary_key=["tag"],
        total_path="totalPages",
        partition_key="dateCreated",
    ),
    "entity_types": CortexEndpointConfig(
        name="entity_types",
        path="/catalog/definitions",
        data_selector="definitions",
        primary_key=["type"],
        total_path="totalPages",
    ),
    "teams": CortexEndpointConfig(
        name="teams",
        path="/teams",
        data_selector="teams",
        primary_key=["id"],
        paginated=False,
    ),
    "relationship_types": CortexEndpointConfig(
        name="relationship_types",
        path="/relationship-types",
        data_selector="relationshipTypes",
        primary_key=["tag"],
        total_path="totalPages",
    ),
    # Fans out over every scorecard and pulls its per-entity scores. `scorecardTag` is only
    # present on the response wrapper (not on each `serviceScores` item), so the parent tag is
    # injected via fan-out and flattened alongside the nested `service` object (see
    # `_flatten_scorecard_score` in cortex.py) to build the composite primary key.
    "scorecard_scores": CortexEndpointConfig(
        name="scorecard_scores",
        path="/scorecards/{tag}/scores",
        data_selector="serviceScores",
        primary_key=["scorecard_tag", "service_tag"],
        total_path="totalPages",
        fanout=DependentEndpointConfig(
            parent_name="scorecards",
            resolve_param="tag",
            resolve_field="tag",
            include_from_parent=["tag"],
            parent_field_renames={"tag": "scorecard_tag"},
        ),
    ),
    # Fans out over every relationship type and pulls its edges. Each row aggregates edges across
    # every type, so the parent's type tag (defensively re-derived via fan-out rather than trusting
    # the row's own echoed `relationshipTypeTag`) plus the flattened source/destination entity tags
    # (see `_flatten_relationship`) keep the key unique table-wide.
    "relationships": CortexEndpointConfig(
        name="relationships",
        path="/relationships/{relationshipTypeTag}",
        data_selector="relationships",
        primary_key=["relationship_type_tag", "source_entity_tag", "destination_entity_tag"],
        total_path="totalPages",
        fanout=DependentEndpointConfig(
            parent_name="relationship_types",
            resolve_param="relationshipTypeTag",
            resolve_field="tag",
            include_from_parent=["tag"],
            parent_field_renames={"tag": "relationship_type_tag"},
        ),
    ),
    "users": CortexEndpointConfig(
        name="users",
        path="/users",
        data_selector="users",
        # The API exposes no user id; email is the documented unique handle for a workspace user.
        primary_key=["email"],
        total_path="totalPages",
        partition_key="joinedAt",
    ),
    # Fans out over every entity and pulls its custom event stream (incidents, migrations,
    # releases). `startTime` filters server-side on the event timestamp, so this is the one
    # Cortex endpoint that can sync incrementally.
    "custom_events": CortexEndpointConfig(
        name="custom_events",
        path="/catalog/{tagOrId}/custom-events",
        data_selector="events",
        primary_key=["entity_id", "uuid"],
        total_path="totalPages",
        partition_key="timestamp",
        incremental_fields=[incremental_field("timestamp")],
        default_incremental_field="timestamp",
        sort_mode="desc",
        fanout=_entity_fanout("tagOrId", {"tag": "entity_tag", "id": "entity_id"}),
    ),
    # Fans out over every entity and pulls its deployment events. The tenant-wide
    # `/deploys/search` endpoint returns the same rows without the entity they belong to, so
    # deploy frequency per entity has to come from the per-entity path.
    "deploys": CortexEndpointConfig(
        name="deploys",
        path="/catalog/{tagOrId}/deploys",
        data_selector="deployments",
        primary_key=["entity_id", "uuid"],
        total_path="totalPages",
        partition_key="timestamp",
        fanout=_entity_fanout("tagOrId", {"tag": "entity_tag", "id": "entity_id"}),
    ),
    # Fans out over every entity and pulls the dependency edges it calls. Each edge is
    # identified by the caller, the callee and the optional endpoint it depends on, and the row
    # carries its own `callerTag`, so the parent identifier is already part of the key.
    "dependencies": CortexEndpointConfig(
        name="dependencies",
        path="/catalog/{callerTag}/dependencies",
        data_selector="dependencies",
        primary_key=["callerTag", "calleeTag", "method", "path"],
        total_path="totalPages",
        fanout=DependentEndpointConfig(
            parent_name="entities",
            resolve_param="callerTag",
            resolve_field="tag_encoded",
            include_from_parent=["id"],
            parent_field_renames={"id": "caller_entity_id"},
            # Outgoing only: an edge is listed by both of its endpoints, so including incoming
            # edges would fetch every edge twice under two different callers.
            child_params={"includeOutgoing": "true", "includeIncoming": "false"},
        ),
    ),
}

ENDPOINTS = tuple(CORTEX_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CORTEX_ENDPOINTS.items()
}
