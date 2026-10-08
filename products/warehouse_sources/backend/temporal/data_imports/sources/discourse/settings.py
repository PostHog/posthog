from dataclasses import field
from typing import Any, Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Verified against a live instance (meta.discourse.org): /latest.json returns 30 topics/page,
# /groups.json returns 20/page, /directory_items.json returns 50/page — all terminate on the
# first short/empty page, so no fixed size is needed for those. /posts.json is fixed at 50 and
# never signals a total, so its cursor paginator needs the page size to decide "last page".
POSTS_PAGE_SIZE = 50

# /admin/users.json is fixed at 100 rows/page server-side and takes no page-size param.
ADMIN_USERS_PAGE_SIZE = 100

# /groups/{name}/members.json caps `limit` at 1000, and /user_actions.json caps it at 100.
GROUP_MEMBERS_PAGE_SIZE = 1000
USER_ACTIONS_PAGE_SIZE = 100

# Ascending by creation date keeps page boundaries stable while the sync runs: a user who
# registers mid-sync lands on the last page instead of shifting every page after them.
ADMIN_USERS_PARAMS = {"order": "created", "asc": "true"}

# Public UserAction types: 1 like, 2 was_liked, 4 new_topic, 5 reply, 6 response, 7 mention,
# 9 quote, 11 edit.
#
# This allowlist is applied to the returned rows, not sent as the `filter` query param.
# Discourse excludes private message topics from the stream only when `filter` is blank, and for
# an admin identity a non-blank `filter` removes that exclusion entirely. Sending the allowlist
# would therefore pull replies, likes and quotes made inside private message topics into the
# table, carrying their titles and excerpts. Leaving `filter` off keeps the topic-level
# exclusion, and the action types are narrowed afterwards.
USER_ACTION_PUBLIC_TYPES = frozenset({1, 2, 4, 5, 6, 7, 9, 11})


@frozen
class DiscourseEndpointConfig:
    name: str
    path: str
    # jsonpath into the response body where the list of records lives. "$" for the endpoints
    # that answer with a bare array.
    data_selector: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # The incremental field to fall back on when the user's schema settings name none.
    default_incremental_field: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # False for endpoints that return their entire collection in one response (verified live —
    # re-requesting categories.json/tags.json with a page param returns the identical full list).
    paginated: bool = False
    # First page number the endpoint accepts. The public list endpoints are 0-based;
    # /admin/users.json is 1-based (it clamps page 0 to page 1, so a 0-based walk would fetch
    # the first 100 users twice).
    first_page: int = 0
    # Rows per page for the endpoints whose paginator sends an explicit page size. 0 where the
    # API fixes the page size itself.
    page_size: int = 0
    # The order rows actually arrive in. Posts return newest-first with no sort override
    # accepted alongside `before` cursor pagination (verified live); user actions are ordered
    # `created_at desc` server-side. Every other endpoint here has no incremental field so
    # ordering doesn't affect a watermark.
    sort_mode: Literal["asc", "desc"] = "asc"
    # A stable, never-changing datetime field to partition on. None disables partitioning.
    partition_key: Optional[str] = None
    # Extra static query params merged into every request (e.g. directory_items' required period).
    extra_params: dict[str, Any] = field(default_factory=dict)
    # Set on endpoints that are fetched once per row of a parent endpoint.
    fanout: Optional[DependentEndpointConfig] = None


# Members are addressed by group name, and Discourse restricts group names to word characters,
# so the name needs no percent-encoding before it goes into the path.
GROUP_MEMBERS_FANOUT = DependentEndpointConfig(
    parent_name="groups",
    resolve_param="name",
    resolve_field="name",
    include_from_parent=["id", "name"],
    parent_field_renames={"id": "group_id", "name": "group_name"},
    # `order=added_at` sorts on the membership row's own creation time, which never changes, so
    # offset pages can't shift under the sync the way the default username ordering can.
    child_params={"order": "added_at", "asc": "true"},
    # A group whose member list is restricted answers 403, and one renamed or deleted between
    # the listing and this fetch answers 404. Every other group still has members worth syncing,
    # so skip the group rather than failing the whole table.
    child_response_actions=[
        {"status_code": 403, "action": "ignore"},
        {"status_code": 404, "action": "ignore"},
    ],
)

# `/user_actions.json` requires a username, so the activity stream is fetched once per user.
# The parent is `admin_users` rather than `users`, because `users` is backed by the
# period-windowed public directory and would miss anyone outside that window.
USER_ACTIONS_FANOUT = DependentEndpointConfig(
    parent_name="admin_users",
    resolve_param="username",
    resolve_field="username",
    # The payload's own `target_user_id` is the user whose stream the row came from, so there
    # is nothing left to carry over from the parent row.
    include_from_parent=[],
    parent_params=dict(ADMIN_USERS_PARAMS),
    # No `filter` param: see USER_ACTION_PUBLIC_TYPES for why the action types are narrowed
    # after the response instead.
    # Discourse answers 404 (not 403) both for a profile the key cannot see and for a user
    # deleted between the listing and this fetch.
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)


# Discourse Admin API endpoints. Only `posts` and `user_actions` have a reliable incremental
# cursor, because both are returned newest-first and are walked back only as far as the watermark.
# Every other list endpoint here has no server-side `updated_since`/`created_after` filter, so
# they stay full refresh (see incrementalSupport research notes: topics/users expose timestamps
# but no since filter).
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
        default_incremental_field="id",
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
    "group_members": DiscourseEndpointConfig(
        name="group_members",
        path="/groups/{name}/members.json",
        # `owners` in the same response is a subset of `members`, not an addition, so syncing
        # `members` alone covers every membership.
        data_selector="members",
        # The member id is a user id, unique only within the group's roster.
        primary_keys=["group_id", "id"],
        paginated=True,
        partition_key="added_at",
        page_size=GROUP_MEMBERS_PAGE_SIZE,
        fanout=GROUP_MEMBERS_FANOUT,
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
    "admin_users": DiscourseEndpointConfig(
        name="admin_users",
        path="/admin/users.json",
        # The response is a bare array of user records.
        data_selector="$",
        paginated=True,
        first_page=1,
        page_size=ADMIN_USERS_PAGE_SIZE,
        partition_key="created_at",
        # `show_emails=true` is available but deliberately not sent: it writes a staff action log
        # entry per request, so a sync of a large forum would bury the customer's own audit log.
        extra_params=dict(ADMIN_USERS_PARAMS),
    ),
    "user_actions": DiscourseEndpointConfig(
        name="user_actions",
        # The user is selected by query param rather than by path segment, and the fan-out
        # builder binds resolve params in the path only, so the param is written into the path.
        path="/user_actions.json?username={username}",
        data_selector="user_actions",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        default_incremental_field="created_at",
        # The stream carries no id of its own. These five columns are what Discourse's own
        # unique index on user_actions is built from, with `post_number` standing in for the
        # nullable target post id so no merge key can be null.
        primary_keys=["target_user_id", "acting_user_id", "action_type", "topic_id", "post_number"],
        paginated=True,
        sort_mode="desc",
        partition_key="created_at",
        page_size=USER_ACTIONS_PAGE_SIZE,
        fanout=USER_ACTIONS_FANOUT,
    ),
    "badges": DiscourseEndpointConfig(
        name="badges",
        path="/admin/badges.json",
        data_selector="badges",
        paginated=False,
    ),
}

ENDPOINTS = tuple(DISCOURSE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DISCOURSE_ENDPOINTS.items() if config.incremental_fields
}
