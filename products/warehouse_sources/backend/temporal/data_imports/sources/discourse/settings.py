from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Verified against a live instance (meta.discourse.org): /latest.json returns 30 topics/page,
# /groups.json returns 20/page, /directory_items.json returns 50/page — all terminate on the
# first short/empty page, so no fixed size is needed for those. /posts.json is fixed at 50 and
# never signals a total, so its cursor paginator needs the page size to decide "last page".
POSTS_PAGE_SIZE = 50


@dataclass
class DiscourseEndpointConfig:
    name: str
    path: str
    # jsonpath into the response body where the list of records lives.
    data_selector: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # False for endpoints that return their entire collection in one response (verified live —
    # re-requesting categories.json/tags.json with a page param returns the identical full list).
    paginated: bool = False
    # The order rows actually arrive in. Posts return newest-first with no sort override
    # accepted alongside `before` cursor pagination (verified live); every other endpoint here
    # has no incremental field so ordering doesn't affect a watermark.
    sort_mode: Literal["asc", "desc"] = "asc"
    # A stable, never-changing datetime field to partition on. None disables partitioning.
    partition_key: Optional[str] = None
    # Extra static query params merged into every request (e.g. directory_items' required period).
    extra_params: dict[str, Any] = field(default_factory=dict)


# Discourse Admin API endpoints. Only `posts` has a reliable incremental cursor (a monotonic
# post id, walked backward via `?before=`) — every other list endpoint here has no server-side
# `updated_since`/`created_after` filter, so they stay full refresh (see incrementalSupport
# research notes: topics/users expose timestamps but no since filter).
DISCOURSE_ENDPOINTS: dict[str, DiscourseEndpointConfig] = {
    "categories": DiscourseEndpointConfig(
        name="categories",
        path="/categories.json",
        # Bare key (not `[*]`): a `[*]` wildcard over an empty array matches nothing, which
        # `data_selector_malformed_retryable` would then treat as a malformed body and retry
        # forever instead of recognizing a legitimate empty/terminal page.
        data_selector="category_list.categories",
        paginated=False,
    ),
    "topics": DiscourseEndpointConfig(
        name="topics",
        path="/latest.json",
        data_selector="topic_list.topics",
        paginated=True,
        partition_key="created_at",
    ),
    "posts": DiscourseEndpointConfig(
        name="posts",
        path="/posts.json",
        data_selector="latest_posts",
        incremental_fields=[
            {
                "label": "id",
                "type": IncrementalFieldType.Integer,
                "field": "id",
                "field_type": IncrementalFieldType.Integer,
            }
        ],
        paginated=True,
        sort_mode="desc",
        partition_key="created_at",
    ),
    "tags": DiscourseEndpointConfig(
        name="tags",
        path="/tags.json",
        data_selector="tags",
        paginated=False,
    ),
    "groups": DiscourseEndpointConfig(
        name="groups",
        path="/groups.json",
        data_selector="groups",
        paginated=True,
    ),
    "users": DiscourseEndpointConfig(
        name="users",
        path="/directory_items.json",
        data_selector="directory_items",
        # `period` is required (the endpoint 400s without it); `order` just needs to be a stable
        # choice so page boundaries don't shift between requests.
        extra_params={"period": "all", "order": "likes_received"},
        paginated=True,
    ),
}

ENDPOINTS = tuple(DISCOURSE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DISCOURSE_ENDPOINTS.items() if config.incremental_fields
}
