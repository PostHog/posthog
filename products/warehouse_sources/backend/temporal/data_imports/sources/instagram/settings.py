from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

# PostHog's Meta app authorizes through Facebook Login, so the Instagram Platform surface is
# reached on graph.facebook.com. (graph.instagram.com serves the same edges, but only for
# tokens minted by Instagram Login.)
GRAPH_API_HOST = "https://graph.facebook.com"

# Node/edge field selections. Meta returns nothing but `id` unless `fields` is passed,
# so every request names its columns explicitly.
ACCOUNT_FIELDS = "id,username,name,biography,website,profile_picture_url,followers_count,follows_count,media_count"
MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,media_url,permalink,thumbnail_url,"
    "timestamp,username,shortcode,like_count,comments_count,is_comment_enabled"
)
STORY_FIELDS = "id,caption,media_type,media_product_type,media_url,permalink,thumbnail_url,timestamp,username"
COMMENT_FIELDS = "id,text,timestamp,username,like_count,hidden"
# Parent listing for the fan-out endpoints — only what the child rows need to be keyed
# and partitioned, so the fan-out doesn't pay for the full media projection.
MEDIA_PARENT_FIELDS = "id,timestamp,media_product_type"
# Page listing used by the account picker. A professional Instagram account is only
# reachable through the Facebook Page it is linked to, so the picker walks the pages.
PAGE_FIELDS = "name,instagram_business_account{id,username,name}"

# Rows per page. Meta caps the media edge at 100 and silently clamps anything larger.
PAGE_SIZE = 100

# Account insights are a daily time series; Meta rejects a since/until span wider than
# 30 days, so a backfill walks the range in windows.
ACCOUNT_INSIGHTS_WINDOW_DAYS = 30
# How far back account insights start when the user gives no start date. Meta only
# retains ~2 years of insights, but a fresh connection defaulting to two years of
# 30-day windows is a lot of calls for data most people don't want.
DEFAULT_INSIGHTS_LOOKBACK_DAYS = 90
# Hard floor on how far back a user-supplied start date can push the account-insights
# backfill. Meta only retains ~2 years of insights anyway, so a start date older than
# this returns nothing but would still fan out into thousands of empty 30-day windows.
MAX_INSIGHTS_LOOKBACK_DAYS = 365 * 2

# Account-level metrics pulled as a daily time series. Meta churns this list per Graph
# version (`impressions` was retired in v22.0 in favour of `views`), so each metric is
# requested on its own and an unsupported one is skipped rather than failing the sync.
ACCOUNT_INSIGHT_METRICS: tuple[str, ...] = ("reach", "views")

# Per-media metrics, keyed by `media_product_type`. Stories expose a different set from
# feed posts and reels.
DEFAULT_MEDIA_INSIGHT_METRICS: tuple[str, ...] = (
    "reach",
    "likes",
    "comments",
    "saved",
    "shares",
    "total_interactions",
    "views",
)
MEDIA_INSIGHT_METRICS: dict[str, tuple[str, ...]] = {
    "FEED": DEFAULT_MEDIA_INSIGHT_METRICS,
    "REELS": DEFAULT_MEDIA_INSIGHT_METRICS,
    "AD": DEFAULT_MEDIA_INSIGHT_METRICS,
    "STORY": ("reach", "replies", "views"),
}


@dataclass
class InstagramEndpointConfig:
    name: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField]
    # Graph edge hung off the Instagram user node. "" means the node itself.
    edge: str = ""
    # `fields` query-string value for the request this endpoint issues.
    fields: str = ""
    # Edge queried once per media node. Set only for fan-out endpoints, which page the
    # media edge as their parent listing.
    child_edge: Optional[str] = None
    # Stable creation timestamp used for partitioning. Never an updated-at column.
    partition_key: Optional[str] = None
    sort_mode: SortMode = "desc"
    # True only where the Graph edge genuinely honours `since`/`until`. Everything else
    # is a full refresh — a client-side filter would still walk every page.
    supports_time_window: bool = False
    # Columns carrying Meta's `+0000` offset, normalized to ISO 8601 on the way out.
    timestamp_fields: tuple[str, ...] = field(default_factory=tuple)


INSTAGRAM_ENDPOINTS: dict[str, InstagramEndpointConfig] = {
    # The professional account itself — one row, refreshed each sync.
    "account": InstagramEndpointConfig(
        name="account",
        edge="",
        fields=ACCOUNT_FIELDS,
        primary_keys=["id"],
        incremental_fields=[],
        sort_mode="asc",
    ),
    # The media edge honours since/until (Unix seconds) against the post's creation
    # time and returns newest-first, so it is the one genuinely incremental collection.
    "media": InstagramEndpointConfig(
        name="media",
        edge="media",
        fields=MEDIA_FIELDS,
        primary_keys=["id"],
        incremental_fields=[incremental_field("timestamp")],
        partition_key="timestamp",
        sort_mode="desc",
        supports_time_window=True,
        timestamp_fields=("timestamp",),
    ),
    # Stories only exist for 24 hours, so there is nothing to sync incrementally.
    "stories": InstagramEndpointConfig(
        name="stories",
        edge="stories",
        fields=STORY_FIELDS,
        primary_keys=["id"],
        incremental_fields=[],
        partition_key="timestamp",
        sort_mode="desc",
        timestamp_fields=("timestamp",),
    ),
    # Comments have no server-side time filter, so the fan-out is a full refresh. The
    # media id is part of the key: the table aggregates comments from every post.
    "media_comments": InstagramEndpointConfig(
        name="media_comments",
        edge="media",
        child_edge="comments",
        fields=COMMENT_FIELDS,
        primary_keys=["media_id", "id"],
        incremental_fields=[],
        partition_key="timestamp",
        sort_mode="desc",
        timestamp_fields=("timestamp",),
    ),
    # One row per (media, metric) in long format — Meta varies the available metrics by
    # media type, so a wide table would be mostly nulls and would break on every
    # Graph version that retires a metric.
    "media_insights": InstagramEndpointConfig(
        name="media_insights",
        edge="media",
        child_edge="insights",
        primary_keys=["media_id", "metric"],
        incremental_fields=[],
        partition_key="media_timestamp",
        sort_mode="desc",
        timestamp_fields=("media_timestamp",),
    ),
    # Daily account metrics, also long format, walked in 30-day windows.
    "account_insights": InstagramEndpointConfig(
        name="account_insights",
        edge="insights",
        primary_keys=["instagram_account_id", "metric", "date"],
        incremental_fields=[incremental_field("date")],
        partition_key="date",
        sort_mode="asc",
        supports_time_window=True,
        timestamp_fields=("date",),
    ),
}

ENDPOINTS = tuple(INSTAGRAM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INSTAGRAM_ENDPOINTS.items()
}
