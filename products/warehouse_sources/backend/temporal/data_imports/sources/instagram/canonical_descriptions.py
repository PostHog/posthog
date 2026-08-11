from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_USER_DOCS = "https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/"
_MEDIA_DOCS = "https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/"
_COMMENT_DOCS = "https://developers.facebook.com/docs/instagram-platform/reference/instagram-comment/"
_INSIGHTS_DOCS = "https://developers.facebook.com/docs/instagram-platform/insights/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "account": {
        "description": "The connected Instagram professional account, refreshed on every sync.",
        "docs_url": _USER_DOCS,
        "columns": {
            "id": "App-scoped Instagram user ID.",
            "username": "The account's Instagram profile username.",
            "name": "The account's Instagram profile name.",
            "biography": "Profile bio text.",
            "website": "The website URL shown on the profile.",
            "profile_picture_url": "URL of the account's profile picture.",
            "followers_count": "Total number of Instagram users following the account.",
            "follows_count": "Total number of Instagram accounts this account follows.",
            "media_count": "Total number of published media on the account.",
        },
    },
    "media": {
        "description": "Posts, reels and carousels published by the account, newest first. Limited to the 10,000 most recently created media.",
        "docs_url": _MEDIA_DOCS,
        "columns": {
            "id": "Media identifier.",
            "caption": "The media's caption text. Excludes @ symbols unless the requester is an admin of the tagged account.",
            "media_type": "Media type: CAROUSEL_ALBUM, IMAGE or VIDEO.",
            "media_product_type": "Surface the media appears on: AD, FEED, STORY or REELS.",
            "media_url": "URL of the media content. Omitted for media flagged for copyright.",
            "permalink": "Permanent URL to the media.",
            "thumbnail_url": "Thumbnail URL. Video content only.",
            "timestamp": "ISO 8601 creation timestamp in UTC.",
            "username": "Username of the account that created the media.",
            "shortcode": "The media's shortcode.",
            "like_count": "Number of likes. Omitted if the owner has hidden like counts.",
            "comments_count": "Number of comments on the media.",
            "is_comment_enabled": "Whether comments are enabled on the media.",
        },
    },
    "stories": {
        "description": "Stories published by the account in the last 24 hours. Instagram deletes stories after 24 hours, so history only accumulates from syncs that ran while a story was live.",
        "docs_url": _MEDIA_DOCS,
        "columns": {
            "id": "Story media identifier.",
            "caption": "The story's caption text.",
            "media_type": "Media type: IMAGE or VIDEO.",
            "media_product_type": "Always STORY for this table.",
            "media_url": "URL of the story content.",
            "permalink": "Permanent URL to the story.",
            "thumbnail_url": "Thumbnail URL. Video stories only.",
            "timestamp": "ISO 8601 creation timestamp in UTC.",
            "username": "Username of the account that published the story.",
        },
    },
    "media_comments": {
        "description": "Comments on the account's media, one row per comment. Keyed by media and comment, because the table aggregates comments across every post.",
        "docs_url": _COMMENT_DOCS,
        "columns": {
            "id": "Comment identifier.",
            "media_id": "Identifier of the media the comment was left on.",
            "text": "The comment's text.",
            "timestamp": "ISO 8601 timestamp of when the comment was posted, in UTC.",
            "username": "Username of the account that left the comment.",
            "like_count": "Number of likes on the comment.",
            "hidden": "Whether the comment is hidden on the media.",
        },
    },
    "media_insights": {
        "description": "Lifetime performance metrics per post, in long format: one row per media and metric. Available metrics vary by media type, and Meta retires metrics between Graph API versions.",
        "docs_url": _INSIGHTS_DOCS,
        "columns": {
            "media_id": "Identifier of the media the metric belongs to.",
            "media_timestamp": "ISO 8601 creation timestamp of the media, in UTC.",
            "media_product_type": "Surface the media appears on: AD, FEED, STORY or REELS.",
            "metric": "Metric name, for example reach, likes, saved, shares, total_interactions or views.",
            "period": "Aggregation period Meta reported the metric over. Media metrics are lifetime totals.",
            "title": "Meta's human-readable title for the metric.",
            "description": "Meta's human-readable description of the metric.",
            "value": "The metric's value.",
        },
    },
    "account_insights": {
        "description": "Daily account-level metrics, in long format: one row per metric and day. Meta only serves insights in windows of at most 30 days and retains roughly two years of history.",
        "docs_url": _INSIGHTS_DOCS,
        "columns": {
            "instagram_account_id": "Instagram account the metric belongs to.",
            "metric": "Metric name, for example reach or views.",
            "period": "Aggregation period. Always day for this table.",
            "date": "ISO 8601 end time of the day the metric covers, in UTC.",
            "value": "The metric's value for that day.",
            "title": "Meta's human-readable title for the metric.",
            "description": "Meta's human-readable description of the metric.",
        },
    },
}
