from dataclasses import dataclass

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.x.com"

API_VERSION_2 = "2"

# X rejects a `start_time` before this instant, so it is the floor for a first incremental run.
EARLIEST_START_TIME = "2010-11-06T00:00:00Z"

# X returns only `id`, `text` and `edit_history_tweet_ids` unless the request asks for more. Every
# name below is readable with an app-only bearer token: `non_public_metrics`, `organic_metrics` and
# `promoted_metrics` need a user context, and a single unreadable name fails the whole request.
POST_FIELDS = ",".join(
    (
        "attachments",
        "author_id",
        "conversation_id",
        "created_at",
        "edit_controls",
        "edit_history_tweet_ids",
        "entities",
        "geo",
        "id",
        "in_reply_to_user_id",
        "lang",
        "note_tweet",
        "possibly_sensitive",
        "public_metrics",
        "referenced_tweets",
        "reply_settings",
        "text",
        "withheld",
    )
)

USER_FIELDS = ",".join(
    (
        "created_at",
        "description",
        "entities",
        "id",
        "location",
        "most_recent_tweet_id",
        "name",
        "pinned_tweet_id",
        "profile_image_url",
        "protected",
        "public_metrics",
        "url",
        "username",
        "verified",
        "verified_type",
        "withheld",
    )
)

LIST_FIELDS = ",".join(
    (
        "created_at",
        "description",
        "follower_count",
        "id",
        "member_count",
        "name",
        "owner_id",
        "private",
    )
)


@dataclass(frozen=True)
class TwitterEndpointConfig:
    name: str
    path: str
    extra_params: dict[str, str]
    page_size: int
    # True for the per-account endpoints, whose path carries the numeric user id. The source form
    # takes a handle, so those paths are formatted after a lookup resolves the handle to an id.
    needs_user_id: bool = True
    primary_key: str = "id"
    partition_key: str | None = None
    # The API's server-side lower-bound filter on the resource's own timestamp. None means the
    # endpoint has no time filter, so it can only sync as a full refresh.
    start_time_param: str | None = None
    # The order rows arrive in. X serves its timelines newest-first and offers no way to reverse
    # them, so the pipeline must not checkpoint the watermark mid-sync.
    sort_mode: SortMode = "asc"


TWITTER_ENDPOINTS: dict[str, TwitterEndpointConfig] = {
    "Profile": TwitterEndpointConfig(
        name="Profile",
        path="/2/users/by",
        extra_params={"user.fields": USER_FIELDS},
        page_size=1,
        needs_user_id=False,
    ),
    "Posts": TwitterEndpointConfig(
        name="Posts",
        path="/2/users/{user_id}/tweets",
        extra_params={"tweet.fields": POST_FIELDS},
        page_size=100,
        partition_key="created_at",
        start_time_param="start_time",
        sort_mode="desc",
    ),
    "Mentions": TwitterEndpointConfig(
        name="Mentions",
        path="/2/users/{user_id}/mentions",
        extra_params={"tweet.fields": POST_FIELDS},
        page_size=100,
        partition_key="created_at",
        start_time_param="start_time",
        sort_mode="desc",
    ),
    "LikedPosts": TwitterEndpointConfig(
        name="LikedPosts",
        path="/2/users/{user_id}/liked_tweets",
        extra_params={"tweet.fields": POST_FIELDS},
        page_size=100,
        partition_key="created_at",
        sort_mode="desc",
    ),
    "Followers": TwitterEndpointConfig(
        name="Followers",
        path="/2/users/{user_id}/followers",
        extra_params={"user.fields": USER_FIELDS},
        page_size=1000,
        partition_key="created_at",
    ),
    "Following": TwitterEndpointConfig(
        name="Following",
        path="/2/users/{user_id}/following",
        extra_params={"user.fields": USER_FIELDS},
        page_size=1000,
        partition_key="created_at",
    ),
    "OwnedLists": TwitterEndpointConfig(
        name="OwnedLists",
        path="/2/users/{user_id}/owned_lists",
        extra_params={"list.fields": LIST_FIELDS},
        page_size=100,
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(TWITTER_ENDPOINTS)

# Only the two timeline endpoints take a server-side `start_time`. The rest page a cursor with no
# time filter, so advertising a cursor field on them would make every run re-read the full list.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field("created_at")] for name, config in TWITTER_ENDPOINTS.items() if config.start_time_param
}
