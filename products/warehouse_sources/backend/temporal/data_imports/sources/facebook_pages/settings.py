from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Graph API resources come in three shapes:
#   "object" -> GET /{page-id} : a single node, no pagination, no time filter.
#   "edge"   -> GET /{page-id}/{edge} : cursor pagination (`paging.cursors.after`) with an
#               optional `since`/`until` filter over `created_time`. Edges return newest-first.
#   "insights" -> GET /{page-id}/insights : a metric time series that must be requested in
#               windows of at most 93 days, flattened into one row per metric/period/end_time.
ResourceStyle = Literal["object", "edge", "insights"]

# Graph API version this source calls. Meta keeps each version alive for ~2 years, so the pin
# is what the request layer builds every URL from.
DEFAULT_API_VERSION = "v23.0"

GRAPH_API_HOST = "https://graph.facebook.com"

# Meta rejects an insights window wider than 93 days, so walk history in chunks under that.
INSIGHTS_WINDOW_DAYS = 90

# How far back the first sync reaches when there is no watermark yet.
DEFAULT_INSIGHTS_LOOKBACK_DAYS = 365

# Scalar (non-breakdown) daily page metrics. Meta retires page metrics regularly and answers a
# request naming a retired one with a 400 that names it, so the request layer drops the named
# metrics and retries rather than failing the whole sync.
PAGE_INSIGHTS_METRICS: tuple[str, ...] = (
    "page_impressions",
    "page_impressions_unique",
    "page_impressions_paid",
    "page_post_engagements",
    "page_fans",
    "page_fan_adds",
    "page_fan_removes",
    "page_views_total",
    "page_daily_follows_unique",
    "page_daily_unfollows_unique",
    "page_video_views",
)


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@frozen
class FacebookPagesEndpointConfig:
    name: str
    style: ResourceStyle
    # Edge name appended to /{page-id}; empty for the page node itself.
    edge: str = ""
    # `fields` query param — Graph returns only id/created_time unless asked.
    fields: tuple[str, ...] = ()
    primary_keys: Optional[list[str]] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Row field the `since`/`until` request filter maps to.
    timestamp_field: Optional[str] = None
    # Edges return newest-first and cursor pagination can't be reordered, so their watermark
    # is only committed once the job finishes.
    sort_mode: Literal["asc", "desc"] = "asc"
    # Stable, immutable field to partition by.
    partition_key: Optional[str] = None
    partition_format: Literal["month", "week", "day", "hour"] = "month"
    description: Optional[str] = None


FACEBOOK_PAGES_ENDPOINTS: dict[str, FacebookPagesEndpointConfig] = {
    "page": FacebookPagesEndpointConfig(
        name="page",
        style="object",
        fields=(
            "id",
            "name",
            "username",
            "about",
            "category",
            "link",
            "website",
            "description",
            "fan_count",
            "followers_count",
            "talking_about_count",
            "is_published",
            "location",
        ),
        primary_keys=["id"],
        description="The Page node itself — one row, refreshed on every sync",
    ),
    "posts": FacebookPagesEndpointConfig(
        name="posts",
        style="edge",
        edge="posts",
        fields=(
            "id",
            "created_time",
            "updated_time",
            "message",
            "story",
            "permalink_url",
            "status_type",
            "is_published",
            "is_hidden",
            "full_picture",
            "icon",
            "shares",
        ),
        primary_keys=["id"],
        incremental_fields=[_datetime_incremental_field("created_time")],
        timestamp_field="created_time",
        sort_mode="desc",
        partition_key="created_time",
        description="Posts published by the Page. Incremental syncs pick up posts created since the last run, not edits to older ones",
    ),
    "videos": FacebookPagesEndpointConfig(
        name="videos",
        style="edge",
        edge="videos",
        fields=(
            "id",
            "created_time",
            "updated_time",
            "title",
            "description",
            "permalink_url",
            "length",
            "published",
            "universal_video_id",
        ),
        primary_keys=["id"],
        incremental_fields=[_datetime_incremental_field("created_time")],
        timestamp_field="created_time",
        sort_mode="desc",
        partition_key="created_time",
        description="Videos uploaded to the Page",
    ),
    "page_insights": FacebookPagesEndpointConfig(
        name="page_insights",
        style="insights",
        edge="insights",
        primary_keys=["page_id", "name", "period", "end_time"],
        incremental_fields=[_datetime_incremental_field("end_time")],
        timestamp_field="end_time",
        sort_mode="asc",
        partition_key="end_time",
        description=(
            f"Daily Page metrics, one row per metric and day. First sync reaches back "
            f"{DEFAULT_INSIGHTS_LOOKBACK_DAYS} days"
        ),
    ),
}

ENDPOINTS = tuple(FACEBOOK_PAGES_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FACEBOOK_PAGES_ENDPOINTS.items()
}
