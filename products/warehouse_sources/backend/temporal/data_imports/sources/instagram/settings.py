from typing import TypedDict

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    PartitionFormat,
    PartitionMode,
    SortMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class InstagramEndpointConfig(TypedDict):
    primary_key: list[str]
    incremental_fields: list[IncrementalField]
    partition_keys: list[str] | None
    partition_mode: PartitionMode | None
    partition_format: PartitionFormat | None
    sort_mode: SortMode
    should_sync_default: bool
    description: str | None


# Field sets requested from the Graph API. Nested objects (`owner`) are flattened
# by the transport; edges (children, insights) are deliberately not requested here.
USER_FIELDS = [
    "id",
    "ig_id",
    "username",
    "name",
    "biography",
    "website",
    "profile_picture_url",
    "followers_count",
    "follows_count",
    "media_count",
]

MEDIA_FIELDS = [
    "id",
    "caption",
    "comments_count",
    "is_comment_enabled",
    "like_count",
    "media_product_type",
    "media_type",
    "media_url",
    "owner",
    "permalink",
    "shortcode",
    "thumbnail_url",
    "timestamp",
    "username",
]

# Stories don't expose engagement counts via fields (insights only) and disappear
# after 24 hours, so each sync sees at most a day's worth.
STORY_FIELDS = [
    "id",
    "caption",
    "media_product_type",
    "media_type",
    "media_url",
    "owner",
    "permalink",
    "shortcode",
    "thumbnail_url",
    "timestamp",
    "username",
]


class InsightMetricConfig(TypedDict):
    name: str
    history_days: int


# Account-level daily insights, fetched one metric at a time as period=day time
# series and stored long-format (one row per account/date/metric). Kept to
# metrics that still support plain period=day time series — much of the newer
# metric surface requires `metric_type=total_value` and is restated frequently.
# `history_days` is the API's own availability floor for the metric.
USER_INSIGHT_METRICS: list[InsightMetricConfig] = [
    {"name": "reach", "history_days": 365},
    # The API only serves follower_count for the trailing 30 days.
    {"name": "follower_count", "history_days": 30},
]

TIMESTAMP_INCREMENTAL_FIELD: IncrementalField = {
    "label": "timestamp",
    "field": "timestamp",
    "type": IncrementalFieldType.DateTime,
    "field_type": IncrementalFieldType.DateTime,
}

DATE_INCREMENTAL_FIELD: IncrementalField = {
    "label": "date",
    "field": "date",
    "type": IncrementalFieldType.Date,
    "field_type": IncrementalFieldType.Date,
}

INSTAGRAM_ENDPOINTS: dict[str, InstagramEndpointConfig] = {
    "users": {
        "primary_key": ["id"],
        "incremental_fields": [],
        "partition_keys": None,
        "partition_mode": None,
        "partition_format": None,
        "sort_mode": "asc",
        "should_sync_default": True,
        "description": "Profile snapshot for each connected Instagram professional account (followers, follows, media count).",
    },
    "media": {
        "primary_key": ["id"],
        "incremental_fields": [TIMESTAMP_INCREMENTAL_FIELD],
        "partition_keys": ["timestamp"],
        "partition_mode": "datetime",
        "partition_format": "month",
        # The media edge always returns newest-first and has no ordering parameter.
        "sort_mode": "desc",
        "should_sync_default": True,
        "description": "All published posts, reels, and videos with engagement counts (likes, comments).",
    },
    "stories": {
        "primary_key": ["id"],
        "incremental_fields": [],
        "partition_keys": None,
        "partition_mode": None,
        "partition_format": None,
        "sort_mode": "desc",
        "should_sync_default": False,
        "description": "Currently live stories. The API only exposes the trailing 24 hours, so this is a rolling snapshot.",
    },
    "user_insights": {
        "primary_key": ["account_id", "date", "metric"],
        "incremental_fields": [DATE_INCREMENTAL_FIELD],
        "partition_keys": ["date"],
        "partition_mode": "datetime",
        "partition_format": "month",
        "sort_mode": "asc",
        "should_sync_default": True,
        "description": "Daily account-level metrics (reach, follower count), one row per account, day, and metric.",
    },
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config["incremental_fields"] for name, config in INSTAGRAM_ENDPOINTS.items()
}
