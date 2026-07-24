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


@dataclass
class FeaturebaseEndpointConfig:
    name: str
    path: str  # Relative to FEATUREBASE_BASE_URL; may carry a {post_id} placeholder for fan-out
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
    # Whether the endpoint paginates with limit/cursor. Boards and post statuses return
    # everything in one response (boards as a bare JSON array, no `data` envelope).
    paginated: bool = True
    partition_key: Optional[str] = None  # Stable creation-time field, never updatedAt
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Fan out one voters request per post ({post_id} placeholder in path).
    fan_out_over_posts: bool = False


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
    # One request per post: materializes the post<->upvoter many-to-many as
    # {postId, ...contact} rows. Opt-in (off by default) because it costs one paginated
    # request chain per post. Voter ids are contact ids (unique per org, not per post),
    # so the composite key keeps rows unique table-wide.
    "post_voters": FeaturebaseEndpointConfig(
        name="post_voters",
        path="/posts/{post_id}/voters",
        fan_out_over_posts=True,
        primary_keys=["postId", "id"],
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(FEATUREBASE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FEATUREBASE_ENDPOINTS.items()
}
