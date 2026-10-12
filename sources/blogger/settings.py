from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class BloggerEndpointConfig:
    name: str
    # Path under the Blogger v3 base URL, with a `{blog_id}` placeholder where needed.
    path: str
    incremental_fields: list[IncrementalField]
    # Stable datetime field to partition by. Blogger's `published` never changes once a post/comment
    # exists, so it's a safe partition key (never use the mutable `updated` field).
    partition_key: Optional[str] = None
    # `orderBy` value to request. Only `posts.list` accepts it; `comments.listByBlog` ignores ordering
    # params and always returns newest-first, so it's left unset there.
    order_by: Optional[str] = None
    # True only where the API exposes a genuine server-side date filter (`startDate`). `posts.list`
    # and `comments.listByBlog` filter on the resource's `published` date; pages/blogs do not.
    supports_incremental: bool = False
    # `blogs.get` returns a single blog object rather than a paginated `items` list.
    is_single_object: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


def _published_incremental_fields() -> list[IncrementalField]:
    # Blogger's `startDate`/`endDate` filter on the resource's post/comment date (`published`), so
    # `published` is the only field we can filter server-side. `published` is also immutable, which
    # makes it a stable cursor that won't rewind.
    return [
        {
            "label": "published",
            "type": IncrementalFieldType.DateTime,
            "field": "published",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


BLOGGER_ENDPOINTS: dict[str, BloggerEndpointConfig] = {
    "blogs": BloggerEndpointConfig(
        name="blogs",
        path="/blogs/{blog_id}",
        incremental_fields=[],
        is_single_object=True,
    ),
    "posts": BloggerEndpointConfig(
        name="posts",
        path="/blogs/{blog_id}/posts",
        partition_key="published",
        order_by="published",
        supports_incremental=True,
        incremental_fields=_published_incremental_fields(),
    ),
    "pages": BloggerEndpointConfig(
        name="pages",
        path="/blogs/{blog_id}/pages",
        incremental_fields=[],
    ),
    "comments": BloggerEndpointConfig(
        name="comments",
        path="/blogs/{blog_id}/comments",
        partition_key="published",
        supports_incremental=True,
        incremental_fields=_published_incremental_fields(),
    ),
}

ENDPOINTS = tuple(BLOGGER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BLOGGER_ENDPOINTS.items()
}
