from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

FEATUREBASE_BASE_URL = "https://do.featurebase.app/v2"
FEATUREBASE_API_VERSION = "2026-01-01.nova"

# Featurebase caps `limit` at 100 on every cursor-paginated list endpoint.
FEATUREBASE_PAGE_SIZE = 100

# Maps PostHog webhook-backed schema name -> the `data.item.object` value of incoming webhook
# payloads, used to route events into the right warehouse table. Deleted-object topics are
# intentionally not subscribed: their payload is the object at deletion time, and merging it
# back on the primary key would resurrect the row. Deletions reconcile on a full refresh.
RESOURCE_TO_FEATUREBASE_OBJECT_TYPE: dict[str, str] = {
    "posts": "post",
    "comments": "comment",
    "changelogs": "changelog",
}

FEATUREBASE_OBJECT_TYPE_TO_TOPICS: dict[str, tuple[str, ...]] = {
    "post": ("post.created", "post.updated"),
    "comment": ("comment.created", "comment.updated"),
    "changelog": ("changelog.published",),
}


@dataclass(frozen=True)
class FeaturebaseFanOutConfig:
    """One child request chain per parent row of `parent_path`."""

    parent_path: str
    # Placeholder in the child endpoint's path, filled with each parent id.
    path_placeholder: str
    # Column the parent id is injected into on every child row.
    parent_id_column: str
    parent_params: dict[str, str] = field(default_factory=dict)
    # Cap on child pages per parent. A cap truncates a genuinely large parent, so only set one
    # where a runaway cursor would multiply across many parents.
    max_pages_per_parent: Optional[int] = None


@dataclass(frozen=True)
class FeaturebaseEndpointConfig:
    name: str
    path: str  # Relative to FEATUREBASE_BASE_URL; may carry a placeholder filled by the fan-out
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # How incremental sync is achieved for this endpoint:
    #   - "desc_cutoff": no server-side timestamp filter exists, but the endpoint supports a
    #     descending sort on the incremental field, so the sweep short-circuits once a whole
    #     page predates the watermark (same pattern as the GitHub source).
    #   - "server_filter": the endpoint accepts a genuine server-side lower-bound param
    #     (changelogs' `startDate`) and an ascending sort, so only new rows are fetched.
    #   - None: full refresh only.
    incremental_mode: Optional[Literal["desc_cutoff", "server_filter"]] = None
    # Maps incremental field name -> the query params that sort by it in the direction the
    # incremental mode needs (descending for "desc_cutoff", ascending for "server_filter").
    incremental_params_for_field: dict[str, dict[str, str]] = field(default_factory=dict)
    # Server-side lower-bound query param for "server_filter" endpoints (changelogs' startDate).
    server_filter_param: Optional[str] = None
    # Query params for a full-refresh run (stable ascending sort where the endpoint has one).
    full_refresh_params: dict[str, str] = field(default_factory=dict)
    # Extra query params merged into every request (e.g. privacy=all).
    extra_params: dict[str, str] = field(default_factory=dict)
    # Whether the endpoint accepts a `limit` query param. Boards, post statuses, ticket
    # statuses and ticket categories return everything in one response as a bare JSON
    # array (no `data` envelope); conversation tags return an enveloped response but,
    # like those, document no query params at all.
    paginated: bool = True
    partition_key: Optional[str] = None  # Stable creation-time field, never updatedAt
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Fan out over a parent listing, one child request chain per parent row.
    fan_out: Optional[FeaturebaseFanOutConfig] = None


_CREATED_AT_FIELD: IncrementalField = {
    "label": "createdAt",
    "type": IncrementalFieldType.DateTime,
    "field": "createdAt",
    "field_type": IncrementalFieldType.DateTime,
}

_UPDATED_AT_FIELD: IncrementalField = {
    "label": "updatedAt",
    "type": IncrementalFieldType.DateTime,
    "field": "updatedAt",
    "field_type": IncrementalFieldType.DateTime,
}

FEATUREBASE_ENDPOINTS: dict[str, FeaturebaseEndpointConfig] = {
    "posts": FeaturebaseEndpointConfig(
        name="posts",
        path="/posts",
        partition_key="createdAt",
        incremental_mode="desc_cutoff",
        # `recent` is documented as "sort by most recently updated"; `createdAt` sorts by
        # creation date. Both accept sortOrder=asc|desc.
        incremental_params_for_field={
            "updatedAt": {"sortBy": "recent", "sortOrder": "desc"},
            "createdAt": {"sortBy": "createdAt", "sortOrder": "desc"},
        },
        full_refresh_params={"sortBy": "createdAt", "sortOrder": "asc"},
        incremental_fields=[_UPDATED_AT_FIELD, _CREATED_AT_FIELD],
    ),
    "comments": FeaturebaseEndpointConfig(
        name="comments",
        path="/comments",
        partition_key="createdAt",
        incremental_mode="desc_cutoff",
        # Comments have their own sort enum: "new" = creation date newest-first,
        # "old" = creation date oldest-first. No updatedAt sort or sortOrder param exists.
        incremental_params_for_field={"createdAt": {"sortBy": "new"}},
        full_refresh_params={"sortBy": "old"},
        # Include admin-only comments; the API key is org-scoped so the caller owns the data.
        extra_params={"privacy": "all"},
        incremental_fields=[_CREATED_AT_FIELD],
    ),
    "changelogs": FeaturebaseEndpointConfig(
        name="changelogs",
        path="/changelogs",
        partition_key="createdAt",
        incremental_mode="server_filter",
        # `startDate` is inclusive ("dated on or after"), so the watermark row is re-pulled
        # and deduped by merge. Only `date` (publication date) is filterable server-side.
        incremental_params_for_field={"date": {"sortBy": "date", "sortOrder": "asc"}},
        server_filter_param="startDate",
        full_refresh_params={"sortBy": "date", "sortOrder": "asc"},
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.DateTime,
                "field": "date",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
    ),
    "boards": FeaturebaseEndpointConfig(
        name="boards",
        path="/boards",
        paginated=False,
    ),
    "post_statuses": FeaturebaseEndpointConfig(
        name="post_statuses",
        path="/post_statuses",
        paginated=False,
    ),
    "custom_fields": FeaturebaseEndpointConfig(
        name="custom_fields",
        path="/custom_fields",
        # Documented as returning everything at once ({data: [...], nextCursor: null});
        # the standard cursor loop terminates on the null cursor either way.
    ),
    "admins": FeaturebaseEndpointConfig(
        name="admins",
        path="/admins",
    ),
    "companies": FeaturebaseEndpointConfig(
        name="companies",
        path="/companies",
        partition_key="createdAt",
    ),
    "contacts": FeaturebaseEndpointConfig(
        name="contacts",
        path="/contacts",
        # Default is customers only; pull leads too so the table covers every identity
        # that can author posts and comments.
        extra_params={"contactType": "all"},
    ),
    "conversations": FeaturebaseEndpointConfig(
        name="conversations",
        path="/conversations",
        partition_key="createdAt",
        # The list endpoint takes only limit/cursor/tagIds — no sort and no timestamp filter —
        # so neither incremental mode applies. The search endpoint can filter on createdAt but
        # returns a slimmer row, which would make the table's columns depend on the sync mode.
    ),
    "tickets": FeaturebaseEndpointConfig(
        name="tickets",
        path="/tickets",
        partition_key="createdAt",
        incremental_mode="desc_cutoff",
        # Only `recent` is documented against a timestamp we sync ("most recently updated",
        # same meaning as on posts). The `date` sort exists too, but which column it orders by
        # is undocumented, and a cutoff sweep on the wrong column silently skips rows.
        incremental_params_for_field={"updatedAt": {"sortBy": "recent", "sortOrder": "desc"}},
        # ticketNumber is the sequential display id, so ascending on it is a stable full-refresh
        # walk regardless of how rows are edited during the sync.
        full_refresh_params={"sortBy": "ticketNumber", "sortOrder": "asc"},
        incremental_fields=[_UPDATED_AT_FIELD],
    ),
    "ticket_statuses": FeaturebaseEndpointConfig(
        name="ticket_statuses",
        path="/tickets/statuses",
        # Documented as returning every status at once, as a bare JSON array like boards.
        paginated=False,
    ),
    "ticket_categories": FeaturebaseEndpointConfig(
        name="ticket_categories",
        path="/tickets/categories",
        # Documented as returning every category at once, as a bare JSON array like boards.
        # Categories are boards behind the scenes, so rows carry `object: "board"`.
        paginated=False,
    ),
    "conversation_tags": FeaturebaseEndpointConfig(
        name="conversation_tags",
        path="/tags",
        # Documented with no query parameters at all (not even limit/cursor) — it's the
        # workspace's whole tag catalog in one enveloped response. Sending `limit` 400s.
        paginated=False,
    ),
    "surveys": FeaturebaseEndpointConfig(
        name="surveys",
        path="/surveys",
        partition_key="createdAt",
        # The list endpoint takes only limit/cursor/type/isActive — no sort and no timestamp
        # filter — so neither incremental mode applies.
    ),
    # One request per post: materializes the post<->upvoter many-to-many as
    # {postId, ...contact} rows. Opt-in (off by default) because it costs one paginated
    # request chain per post. Voter ids are contact ids (unique per org, not per post),
    # so the composite key keeps rows unique table-wide.
    "post_voters": FeaturebaseEndpointConfig(
        name="post_voters",
        path="/posts/{post_id}/voters",
        fan_out=FeaturebaseFanOutConfig(
            parent_path="/posts",
            path_placeholder="post_id",
            parent_id_column="postId",
            parent_params={"sortBy": "createdAt", "sortOrder": "asc"},
            max_pages_per_parent=100,
        ),
        primary_keys=["postId", "id"],
        should_sync_default=False,
    ),
    # One request per survey: materializes each submitted response as a
    # {surveyId, ...response} row. The responses endpoint takes only pageId/limit/cursor, so
    # there is no incremental filter. Response ids are documented as optional on the nested
    # answers but required on the response itself; the composite key keeps rows unique
    # table-wide in case they are only unique per survey.
    "survey_responses": FeaturebaseEndpointConfig(
        name="survey_responses",
        path="/surveys/{survey_id}/responses",
        partition_key="createdAt",
        fan_out=FeaturebaseFanOutConfig(
            parent_path="/surveys",
            path_placeholder="survey_id",
            parent_id_column="surveyId",
        ),
        primary_keys=["surveyId", "id"],
    ),
}

ENDPOINTS = tuple(FEATUREBASE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FEATUREBASE_ENDPOINTS.items()
}
