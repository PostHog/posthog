from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

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
MEDIA_PAGE_SAFE_FIELDS = (
    "id,caption,media_type,media_product_type,media_url,permalink,thumbnail_url,"
    "timestamp,username,shortcode,like_count,comments_count,is_comment_enabled"
)
# Meta refuses a whole media page when one post on it is a video Meta can no longer find and the
# page asks for one of these fields. A refused page is read again with the safe fields only, and
# each of its posts then reads these fields on its own (see `_media_page`).
MEDIA_REFUSABLE_FIELDS = (
    "is_shared_to_feed,owner,boost_ads_list,boost_eligibility_info,copyright_check_information,"
    "legacy_instagram_media_id"
)
MEDIA_FIELDS = f"{MEDIA_PAGE_SAFE_FIELDS},{MEDIA_REFUSABLE_FIELDS}"
STORY_FIELDS = "id,caption,media_type,media_product_type,media_url,permalink,thumbnail_url,timestamp,username"
COMMENT_FIELDS = "id,text,timestamp,username,like_count,hidden,parent_id,from"
# The media comments edge lists top-level comments only. Expanding `replies` inline brings
# the first page of each thread back on the same request, so a thread costs an extra call
# only when it overflows that page.
TOP_LEVEL_COMMENT_FIELDS = f"{COMMENT_FIELDS},replies.limit(100){{{COMMENT_FIELDS}}}"
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

# Account-level metrics. Meta churns this list per Graph version (`impressions` was
# retired in v22.0 in favour of `views`), so each metric is requested on its own and an
# unsupported one is skipped rather than failing the sync.
# `reach` is the only one Meta serves as a daily time series.
ACCOUNT_INSIGHT_TIME_SERIES_METRICS: tuple[str, ...] = ("reach",)
# Meta serves these only with `metric_type=total_value`, which sums the whole since/until
# span into one value. Each one is requested once per day to get a daily row.
ACCOUNT_INSIGHT_TOTAL_VALUE_METRICS: tuple[str, ...] = (
    "views",
    "accounts_engaged",
    "total_interactions",
    "likes",
    "comments",
    "shares",
    "saves",
    "replies",
    "profile_links_taps",
    "follows_and_unfollows",
)
# `(metric, breakdown)` pairs for `account_insights_breakdowns`. Each pair is requested
# with `metric_type=total_value` once per day, like the metrics above.
ACCOUNT_INSIGHT_BREAKDOWNS: tuple[tuple[str, str], ...] = (
    ("follows_and_unfollows", "follow_type"),
    ("likes", "media_product_type"),
    ("comments", "media_product_type"),
    ("shares", "media_product_type"),
    ("saves", "media_product_type"),
    ("total_interactions", "media_product_type"),
    ("profile_links_taps", "contact_button_type"),
)

# Per-media metrics, keyed by `media_product_type`. Each list must match Meta's media
# insights table exactly: one metric that does not apply to the post fails the whole
# request, and the sync then skips every metric for that post.
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
    "FEED": (*DEFAULT_MEDIA_INSIGHT_METRICS, "follows", "profile_visits"),
    "REELS": (*DEFAULT_MEDIA_INSIGHT_METRICS, "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"),
    "AD": DEFAULT_MEDIA_INSIGHT_METRICS,
    "STORY": ("reach", "replies", "views", "follows", "profile_visits"),
}

# Per-media `(metric, breakdown)` pairs, keyed by `media_product_type`. Meta rejects a
# breakdown on a metric that does not support it, so each pair is a separate request.
MEDIA_INSIGHT_BREAKDOWNS: dict[str, tuple[tuple[str, str], ...]] = {
    "FEED": (("profile_activity", "action_type"),),
    "STORY": (
        ("profile_activity", "action_type"),
        ("navigation", "story_navigation_action_type"),
    ),
}


@frozen
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
    # Account insight requests for each window: daily time series metrics, then
    # `(metric, breakdown)` pairs asked for as `total_value` once per day.
    insight_time_series_metrics: tuple[str, ...] = field(default_factory=tuple)
    insight_total_value_metrics: tuple[tuple[str, Optional[str]], ...] = field(default_factory=tuple)


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
    # media id is part of the key: the table aggregates comments from every post. Replies
    # land in the same table with `parent_id` set to the top-level comment.
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
    # One row per (media, metric, breakdown value). Only feed posts and stories have
    # breakdowns, so other media issue no request.
    "media_insights_breakdowns": InstagramEndpointConfig(
        name="media_insights_breakdowns",
        edge="media",
        child_edge="insights",
        primary_keys=["media_id", "metric", "breakdown", "breakdown_value"],
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
        insight_time_series_metrics=ACCOUNT_INSIGHT_TIME_SERIES_METRICS,
        insight_total_value_metrics=tuple((metric, None) for metric in ACCOUNT_INSIGHT_TOTAL_VALUE_METRICS),
    ),
    # Daily account metrics split by a breakdown dimension. A separate table, so the key
    # of `account_insights` stays the same for existing syncs.
    "account_insights_breakdowns": InstagramEndpointConfig(
        name="account_insights_breakdowns",
        edge="insights",
        primary_keys=["instagram_account_id", "metric", "breakdown", "breakdown_value", "date"],
        incremental_fields=[incremental_field("date")],
        partition_key="date",
        sort_mode="asc",
        supports_time_window=True,
        timestamp_fields=("date",),
        insight_total_value_metrics=ACCOUNT_INSIGHT_BREAKDOWNS,
    ),
}

ENDPOINTS = tuple(INSTAGRAM_ENDPOINTS.keys())
ENDPOINTS_REREAD_EVERY_SYNC: frozenset[str] = frozenset({"media"})

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INSTAGRAM_ENDPOINTS.items()
}
