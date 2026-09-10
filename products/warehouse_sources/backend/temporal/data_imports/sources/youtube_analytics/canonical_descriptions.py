from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.settings import (
    CHANNEL_DAILY,
    DEMOGRAPHICS,
    DEVICE_TYPES,
    GEOGRAPHY,
    OPERATING_SYSTEMS,
    PLAYBACK_LOCATIONS,
    SHARING_SERVICES,
    SUBSCRIBED_STATUS,
    TOP_VIDEOS,
    TRAFFIC_SOURCES,
)

_METRICS_DOCS_URL = "https://developers.google.com/youtube/analytics/metrics"
_DIMENSIONS_DOCS_URL = "https://developers.google.com/youtube/analytics/dimensions"

_DAY = "The date the activity occurred, as UTC midnight."
_VIEWS = "The number of times the channel's videos were viewed."
_ESTIMATED_MINUTES_WATCHED = "The number of minutes that users watched the channel's videos."
_AVERAGE_VIEW_DURATION = "The average length, in seconds, of a video playback."
_AVERAGE_VIEW_PERCENTAGE = "The average percentage of a video watched during a playback."
_SUBSCRIBERS_GAINED = "The number of times that users subscribed to the channel."
_SUBSCRIBERS_LOST = "The number of times that users unsubscribed from the channel."
_LIKES = "The number of times that users indicated they liked a video by giving it a positive rating."
_DISLIKES = "The number of times that users indicated they disliked a video by giving it a negative rating."
_COMMENTS = "The number of times that users commented on a video."
_SHARES = "The number of times that users shared a video through the Share button."

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    CHANNEL_DAILY: {
        "description": "Daily channel-level user activity: views, watch time, engagement and subscriber changes.",
        "docs_url": _METRICS_DOCS_URL,
        "columns": {
            "day": _DAY,
            "views": _VIEWS,
            "redViews": "The number of times the channel's videos were viewed by YouTube Premium members.",
            "comments": _COMMENTS,
            "likes": _LIKES,
            "dislikes": _DISLIKES,
            "shares": _SHARES,
            "estimatedMinutesWatched": _ESTIMATED_MINUTES_WATCHED,
            "estimatedRedMinutesWatched": "The number of minutes that YouTube Premium members watched the channel's videos.",
            "averageViewDuration": _AVERAGE_VIEW_DURATION,
            "averageViewPercentage": _AVERAGE_VIEW_PERCENTAGE,
            "subscribersGained": _SUBSCRIBERS_GAINED,
            "subscribersLost": _SUBSCRIBERS_LOST,
            "videosAddedToPlaylists": "The number of times the channel's videos were added to any YouTube playlist.",
            "videosRemovedFromPlaylists": "The number of times the channel's videos were removed from any YouTube playlist.",
        },
    },
    TOP_VIDEOS: {
        "description": "The channel's top videos for each day, ranked by watch time (up to 200 videos per day).",
        "docs_url": _DIMENSIONS_DOCS_URL,
        "columns": {
            "day": _DAY,
            "video": "The YouTube video ID the metrics describe.",
            "views": _VIEWS,
            "estimatedMinutesWatched": _ESTIMATED_MINUTES_WATCHED,
            "averageViewDuration": _AVERAGE_VIEW_DURATION,
            "averageViewPercentage": _AVERAGE_VIEW_PERCENTAGE,
            "likes": _LIKES,
            "dislikes": _DISLIKES,
            "comments": _COMMENTS,
            "shares": _SHARES,
            "subscribersGained": _SUBSCRIBERS_GAINED,
            "subscribersLost": _SUBSCRIBERS_LOST,
        },
    },
    TRAFFIC_SOURCES: {
        "description": "Daily views and watch time broken down by the referrer type that led viewers to the videos.",
        "docs_url": _DIMENSIONS_DOCS_URL,
        "columns": {
            "day": _DAY,
            "insightTrafficSourceType": "The referrer type that led viewers to the video, such as YT_SEARCH, SUBSCRIBER or EXT_URL.",
            "views": _VIEWS,
            "estimatedMinutesWatched": _ESTIMATED_MINUTES_WATCHED,
        },
    },
    PLAYBACK_LOCATIONS: {
        "description": "Daily views and watch time broken down by the type of page or application where playback occurred.",
        "docs_url": _DIMENSIONS_DOCS_URL,
        "columns": {
            "day": _DAY,
            "insightPlaybackLocationType": "The type of page or application where the playback occurred, such as WATCH, EMBEDDED or CHANNEL.",
            "views": _VIEWS,
            "estimatedMinutesWatched": _ESTIMATED_MINUTES_WATCHED,
        },
    },
    DEVICE_TYPES: {
        "description": "Daily views and watch time broken down by the form factor of the device used for playback.",
        "docs_url": _DIMENSIONS_DOCS_URL,
        "columns": {
            "day": _DAY,
            "deviceType": "The physical form factor of the device where the playback occurred, such as MOBILE, DESKTOP or TV.",
            "views": _VIEWS,
            "estimatedMinutesWatched": _ESTIMATED_MINUTES_WATCHED,
        },
    },
    OPERATING_SYSTEMS: {
        "description": "Daily views and watch time broken down by the operating system of the playback device.",
        "docs_url": _DIMENSIONS_DOCS_URL,
        "columns": {
            "day": _DAY,
            "operatingSystem": "The software system of the device where the playback occurred, such as ANDROID, IOS or WINDOWS.",
            "views": _VIEWS,
            "estimatedMinutesWatched": _ESTIMATED_MINUTES_WATCHED,
        },
    },
    GEOGRAPHY: {
        "description": "Daily views, watch time and subscriber changes broken down by viewer country.",
        "docs_url": _DIMENSIONS_DOCS_URL,
        "columns": {
            "day": _DAY,
            "country": "The ISO 3166-1 alpha-2 country code the metrics are associated with.",
            "views": _VIEWS,
            "estimatedMinutesWatched": _ESTIMATED_MINUTES_WATCHED,
            "averageViewDuration": _AVERAGE_VIEW_DURATION,
            "averageViewPercentage": _AVERAGE_VIEW_PERCENTAGE,
            "subscribersGained": _SUBSCRIBERS_GAINED,
            "subscribersLost": _SUBSCRIBERS_LOST,
        },
    },
    DEMOGRAPHICS: {
        "description": "Daily viewer distribution across age group and gender, for signed-in viewers only.",
        "docs_url": _DIMENSIONS_DOCS_URL,
        "columns": {
            "day": _DAY,
            "ageGroup": "The age group of the signed-in viewers, such as age18-24.",
            "gender": "The gender of the signed-in viewers.",
            "viewerPercentage": "The percentage of signed-in viewers that fall into this age group and gender.",
        },
    },
    SHARING_SERVICES: {
        "description": "Daily share counts broken down by the service videos were shared to.",
        "docs_url": _DIMENSIONS_DOCS_URL,
        "columns": {
            "day": _DAY,
            "sharingService": "The service used to share the video, such as WHATSAPP, COPY_PASTE or FACEBOOK.",
            "shares": _SHARES,
        },
    },
    SUBSCRIBED_STATUS: {
        "description": "Daily views and watch time split by whether the viewer was subscribed to the channel.",
        "docs_url": _DIMENSIONS_DOCS_URL,
        "columns": {
            "day": _DAY,
            "subscribedStatus": "Whether the viewer was subscribed to the channel when the activity occurred.",
            "views": _VIEWS,
            "estimatedMinutesWatched": _ESTIMATED_MINUTES_WATCHED,
        },
    },
}
