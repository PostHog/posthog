from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# The YouTube Analytics API is a single global host; `reports.query` is the only endpoint we call.
YOUTUBE_ANALYTICS_HOST = "https://youtubeanalytics.googleapis.com"

# The YouTube Data API, used only to list the channels the connected account owns.
YOUTUBE_DATA_HOST = "https://www.googleapis.com/youtube/v3"

# Scopes the connected Google account must grant. `yt-analytics-monetary.readonly` is deliberately
# not among them: channel reports carry no revenue metrics, so it would grant nothing we read.
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
REQUIRED_SCOPES = f"{ANALYTICS_SCOPE} {YOUTUBE_READONLY_SCOPE}"

# `reports.query` caps a response at 200 rows and pages with a 1-based `startIndex`.
MAX_RESULTS_PER_PAGE = 200

# `channels.list?mine=true` returns only the channels the connected account owns, which is one for
# an ordinary Google account, so the API's page maximum covers the list without paging.
MAX_CHANNELS_PER_PAGE = 50

# YouTube keeps revising the most recent days for a while, and the current day is always
# partial, so the sync stops short of today and re-reads a trailing window every run.
DATA_LATENCY_DAYS = 1
REVISION_LOOKBACK_SECONDS = 3 * 24 * 60 * 60

# Reports that carry `day` as a report dimension answer a multi-day window in one request.
# Everything else aggregates over the query window, so those are asked one day at a time.
DAY_DIMENSION_WINDOW_DAYS = 90

# First sync horizon when the user doesn't pin a start date.
DEFAULT_LOOKBACK_DAYS = 365

# Earliest start date we accept. YouTube Analytics has no channel data before 2008, and each
# report walks the range one day (or one 90-day window) at a time, so a date further back just
# fans out empty requests — bound it to keep a stray start date from spawning a runaway backfill.
MIN_START_DATE = "2008-01-01"

CHANNEL_DAILY = "channel_daily"
TOP_VIDEOS = "top_videos"
TRAFFIC_SOURCES = "traffic_sources"
PLAYBACK_LOCATIONS = "playback_locations"
DEVICE_TYPES = "device_types"
OPERATING_SYSTEMS = "operating_systems"
GEOGRAPHY = "geography"
DEMOGRAPHICS = "demographics"
SHARING_SERVICES = "sharing_services"
SUBSCRIBED_STATUS = "subscribed_status"

# Every row carries the day it describes, either from the report's own `day` dimension or
# stamped from the one-day query window.
DAY_FIELD = "day"


@dataclass(frozen=True)
class YouTubeAnalyticsReportConfig:
    name: str
    # Report dimensions besides the day. Empty means channel-level totals.
    dimensions: tuple[str, ...]
    metrics: tuple[str, ...]
    # True when `day` is requested as a report dimension so one request covers a window of
    # days; False when the report only aggregates over the window and we window per day.
    day_is_dimension: bool = False
    sort: str | None = None
    # `video`-keyed reports are "top N" reports: YouTube caps them at 200 rows and requires
    # an explicit sort, so we take the single page rather than paging into a cap.
    single_page: bool = False

    @property
    def primary_keys(self) -> list[str]:
        return [DAY_FIELD, *self.dimensions]


YOUTUBE_ANALYTICS_REPORTS: dict[str, YouTubeAnalyticsReportConfig] = {
    CHANNEL_DAILY: YouTubeAnalyticsReportConfig(
        name=CHANNEL_DAILY,
        dimensions=(),
        metrics=(
            "views",
            "redViews",
            "comments",
            "likes",
            "dislikes",
            "shares",
            "estimatedMinutesWatched",
            "estimatedRedMinutesWatched",
            "averageViewDuration",
            "averageViewPercentage",
            "subscribersGained",
            "subscribersLost",
            "videosAddedToPlaylists",
            "videosRemovedFromPlaylists",
        ),
        day_is_dimension=True,
        sort="day",
    ),
    TOP_VIDEOS: YouTubeAnalyticsReportConfig(
        name=TOP_VIDEOS,
        dimensions=("video",),
        metrics=(
            "views",
            "estimatedMinutesWatched",
            "averageViewDuration",
            "averageViewPercentage",
            "likes",
            "dislikes",
            "comments",
            "shares",
            "subscribersGained",
            "subscribersLost",
        ),
        sort="-estimatedMinutesWatched",
        single_page=True,
    ),
    TRAFFIC_SOURCES: YouTubeAnalyticsReportConfig(
        name=TRAFFIC_SOURCES,
        dimensions=("insightTrafficSourceType",),
        metrics=("views", "estimatedMinutesWatched"),
    ),
    PLAYBACK_LOCATIONS: YouTubeAnalyticsReportConfig(
        name=PLAYBACK_LOCATIONS,
        dimensions=("insightPlaybackLocationType",),
        metrics=("views", "estimatedMinutesWatched"),
    ),
    DEVICE_TYPES: YouTubeAnalyticsReportConfig(
        name=DEVICE_TYPES,
        dimensions=("deviceType",),
        metrics=("views", "estimatedMinutesWatched"),
    ),
    OPERATING_SYSTEMS: YouTubeAnalyticsReportConfig(
        name=OPERATING_SYSTEMS,
        dimensions=("operatingSystem",),
        metrics=("views", "estimatedMinutesWatched"),
    ),
    GEOGRAPHY: YouTubeAnalyticsReportConfig(
        name=GEOGRAPHY,
        dimensions=("country",),
        metrics=(
            "views",
            "estimatedMinutesWatched",
            "averageViewDuration",
            "averageViewPercentage",
            "subscribersGained",
            "subscribersLost",
        ),
    ),
    DEMOGRAPHICS: YouTubeAnalyticsReportConfig(
        name=DEMOGRAPHICS,
        dimensions=("ageGroup", "gender"),
        metrics=("viewerPercentage",),
    ),
    SHARING_SERVICES: YouTubeAnalyticsReportConfig(
        name=SHARING_SERVICES,
        dimensions=("sharingService",),
        metrics=("shares",),
    ),
    SUBSCRIBED_STATUS: YouTubeAnalyticsReportConfig(
        name=SUBSCRIBED_STATUS,
        dimensions=("subscribedStatus",),
        metrics=("views", "estimatedMinutesWatched"),
    ),
}

ENDPOINTS = tuple(YOUTUBE_ANALYTICS_REPORTS.keys())

# Every report is filtered server-side by `startDate`/`endDate`, so the day is a real
# incremental cursor for all of them.
DAY_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": DAY_FIELD,
        "type": IncrementalFieldType.DateTime,
        "field": DAY_FIELD,
        "field_type": IncrementalFieldType.DateTime,
    }
]

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = dict.fromkeys(ENDPOINTS, DAY_INCREMENTAL_FIELDS)
