from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.settings import (
    DATA_LATENCY_DAYS,
    DAY_DIMENSION_WINDOW_DAYS,
    DAY_FIELD,
    DEFAULT_LOOKBACK_DAYS,
    FULL_REFRESH_PRIMARY_KEYS,
    MAX_CHANNELS_PER_PAGE,
    MAX_PER_VIDEO_REPORT_VIDEOS,
    MAX_PLAYLISTS_PER_PAGE,
    MAX_VIDEOS_PER_PAGE,
    MIN_START_DATE,
    PER_VIDEO_REPORTS,
    VIDEO_PARTS,
    VIDEOS,
    YOUTUBE_ANALYTICS_HOST,
    YOUTUBE_ANALYTICS_REPORTS,
    YOUTUBE_DATA_HOST,
    YouTubeAnalyticsReportConfig,
    YouTubeAnalyticsVideoReportConfig,
)

REQUEST_TIMEOUT_SECONDS = 120
DEFAULT_API_VERSION = "v2"

# Called to mint a fresh access token when the current one is rejected mid-sync.
AccessTokenRefresher = Callable[[], str]


@frozen
class YouTubeAnalyticsResumeConfig:
    # ISO date (YYYY-MM-DD) of the next day-window to request.
    next_start_date: str


class YouTubeAnalyticsAuthError(Exception):
    """The connected Google account's credentials were rejected or could not be refreshed."""


def channel_ids_param(channel_id: str | None) -> str:
    """The `ids` filter for `reports.query` — the authorized channel unless one is pinned."""
    cleaned = (channel_id or "").strip()
    return f"channel=={cleaned}" if cleaned else "channel==MINE"


def coerce_day(value: Any) -> Optional[datetime]:
    """Normalize a YouTube `day` value (or a stored watermark) to a UTC midnight datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def rows_from_result(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Zip `reports.query`'s positional rows against its `columnHeaders` into dicts."""
    headers = [header.get("name") for header in body.get("columnHeaders") or []]
    if not headers:
        return []
    return [dict(zip(headers, row)) for row in body.get("rows") or []]


class YouTubeAnalyticsClient:
    """Queries `reports.query` and the YouTube Data API with the connected Google account's access token."""

    def __init__(
        self,
        access_token: str,
        refresh_access_token: AccessTokenRefresher | None = None,
        api_version: str = DEFAULT_API_VERSION,
        logger: FilteringBoundLogger | None = None,
    ) -> None:
        self._token = access_token
        self._refresh_access_token = refresh_access_token
        self._api_version = api_version
        self._logger = logger
        # The token rides the `Authorization` header, which the tracked transport already scrubs.
        # capture=False: report bodies are positional rows (top videos, geography, demographics,
        # engagement) with no field names for the scrubber to match on, so they stay out of
        # diagnostic HTTP samples entirely. Requests are still metered and logged.
        self._session = make_tracked_session(capture=False)

    @property
    def reports_url(self) -> str:
        return f"{YOUTUBE_ANALYTICS_HOST}/{self._api_version}/reports"

    def query(self, params: dict[str, str]) -> dict[str, Any]:
        return self.get_json(f"{self.reports_url}?{urlencode(params)}")

    def get_json(self, url: str) -> dict[str, Any]:
        def _get(token: str) -> requests.Response:
            return self._session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        response = _get(self._token)
        # Google access tokens last ~1h; a long backfill can outlive one, so refresh once on 401.
        if response.status_code == 401 and self._refresh_access_token is not None:
            self._token = self._refresh_access_token()
            response = _get(self._token)

        if not response.ok:
            if self._logger is not None:
                self._logger.error(
                    f"YouTube Analytics API error: status={response.status_code}, body={response.text[:500]}"
                )
            response.raise_for_status()

        return response.json()


def min_start_day() -> date:
    return datetime.strptime(MIN_START_DATE, "%Y-%m-%d").date()


def validate_start_date(start_date: str | None) -> tuple[bool, Optional[str]]:
    """Reject a pinned start date that predates YouTube Analytics data or sits in the future — an
    unbounded historical range fans out into one request per day per report."""
    if not start_date:
        return True, None
    parsed = coerce_day(start_date)
    if parsed is None:
        return False, f"Invalid start date '{start_date}'. Use the format YYYY-MM-DD."
    if parsed.date() < min_start_day():
        return False, f"Start date must be on or after {MIN_START_DATE}."
    if parsed.date() > datetime.now(UTC).date():
        return False, "Start date can't be in the future."
    return True, None


def list_channels(access_token: str) -> list[dict[str, Any]]:
    """Channels the connected Google account owns, so the user picks one instead of hunting for its ID."""
    # capture=False: the channel list carries customer-owned channel titles and descriptions, so it
    # stays out of diagnostic HTTP samples for the same reason report bodies do.
    session = make_tracked_session(capture=False)
    params = {"part": "snippet", "mine": "true", "maxResults": str(MAX_CHANNELS_PER_PAGE)}
    response = session.get(
        f"{YOUTUBE_DATA_HOST}/channels?{urlencode(params)}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json().get("items") or []


def validate_credentials(
    access_token: str,
    channel_id: str | None = None,
    start_date: str | None = None,
    api_version: str = DEFAULT_API_VERSION,
) -> tuple[bool, Optional[str]]:
    ok, message = validate_start_date(start_date)
    if not ok:
        return False, message

    client = YouTubeAnalyticsClient(access_token, api_version=api_version)

    yesterday = (datetime.now(UTC) - timedelta(days=DATA_LATENCY_DAYS)).date()
    try:
        client.query(
            {
                "ids": channel_ids_param(channel_id),
                "startDate": yesterday.isoformat(),
                "endDate": yesterday.isoformat(),
                "metrics": "views",
                "maxResults": "1",
            }
        )
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 401:
            return False, "Google rejected the connected account's credentials. Please reconnect the integration."
        if status == 403:
            return (
                False,
                "The connected Google account cannot read this channel's analytics. Reconnect using an "
                "account that manages the channel, and grant the YouTube Analytics permission.",
            )
        if status == 400:
            return False, "YouTube rejected the channel. Pick a channel the connected account owns."
        return False, f"Unexpected response from the YouTube Analytics API (status {status})."
    except Exception as e:
        return False, f"Could not reach the YouTube Analytics API ({e}). Please retry."

    return True, None


def resolve_start_day(
    start_date: str | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    today: date,
) -> date:
    """Earliest day to request: the stored watermark when syncing incrementally, else the
    user's pinned start date, else a bounded first-sync horizon."""
    configured = coerce_day(start_date)
    # Clamp to the supported floor so a start date saved before that guard existed still can't
    # walk the range back before YouTube has data.
    floor = max(
        configured.date() if configured else today - timedelta(days=DEFAULT_LOOKBACK_DAYS),
        min_start_day(),
    )

    if should_use_incremental_field:
        watermark = coerce_day(db_incremental_field_last_value)
        if watermark is not None:
            return max(floor, watermark.date())

    return floor


def _fetch_window(
    client: YouTubeAnalyticsClient,
    report: YouTubeAnalyticsReportConfig,
    ids: str,
    window_start: date,
    window_end: date,
    filter_value: str | None = None,
) -> list[dict[str, Any]]:
    dimensions = ((DAY_FIELD,) if report.day_is_dimension else ()) + report.dimensions
    stamped_day = coerce_day(window_start)
    collected: list[dict[str, Any]] = []
    start_index = 1

    while True:
        params = {
            "ids": ids,
            "startDate": window_start.isoformat(),
            "endDate": window_end.isoformat(),
            "metrics": ",".join(report.metrics),
            "maxResults": str(report.max_results),
            "startIndex": str(start_index),
        }
        if dimensions:
            params["dimensions"] = ",".join(dimensions)
        if report.sort:
            params["sort"] = report.sort
        if report.filter_dimension and filter_value is not None:
            params["filters"] = f"{report.filter_dimension}=={filter_value}"

        rows = rows_from_result(client.query(params))
        for row in rows:
            row[DAY_FIELD] = coerce_day(row.get(DAY_FIELD)) if report.day_is_dimension else stamped_day
            if report.filter_dimension and filter_value is not None:
                row[report.filter_dimension] = filter_value
        collected.extend(rows)

        if report.single_page or len(rows) < report.max_results:
            break
        start_index += len(rows)

    return collected


def _playlist_ids(
    client: YouTubeAnalyticsClient,
    channel_id: str | None,
    resumable_source_manager: ResumableSourceManager[YouTubeAnalyticsResumeConfig],
) -> list[str]:
    """IDs of the playlists the channel owns. Playlist reports only cover the owner's playlists."""
    params = {"part": "id", "maxResults": str(MAX_PLAYLISTS_PER_PAGE)}
    cleaned = (channel_id or "").strip()
    if cleaned:
        params["channelId"] = cleaned
    else:
        params["mine"] = "true"
    # A playlist created mid-walk shifts the list, which can repeat a playlist on the next page.
    playlist_ids: dict[str, None] = {}
    while True:
        body = client.get_json(f"{YOUTUBE_DATA_HOST}/playlists?{urlencode(params)}")
        for item in body.get("items") or []:
            if item.get("id"):
                playlist_ids[item["id"]] = None
        page_token = body.get("nextPageToken")
        if not page_token:
            return list(playlist_ids)
        params["pageToken"] = page_token
        # No report row has been read yet, so a hand-off here loses nothing.
        resumable_source_manager.safe_point()


def get_rows(
    access_token: str,
    refresh_access_token: AccessTokenRefresher | None,
    channel_id: str | None,
    start_date: str | None,
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[YouTubeAnalyticsResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    report = YOUTUBE_ANALYTICS_REPORTS[endpoint]
    client = YouTubeAnalyticsClient(
        access_token, refresh_access_token=refresh_access_token, api_version=api_version, logger=logger
    )
    ids = channel_ids_param(channel_id)

    today = datetime.now(UTC).date()
    # Today is always partial and YouTube keeps revising the last couple of days, so stop short.
    end_day = today - timedelta(days=DATA_LATENCY_DAYS)
    cursor = resolve_start_day(start_date, should_use_incremental_field, db_incremental_field_last_value, today)

    # A persisted resume cursor wins so a heartbeat-timed-out activity picks up where it stopped.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        resumed = coerce_day(resume.next_start_date)
        if resumed is not None:
            cursor = resumed.date()
            logger.debug(f"YouTube Analytics: resuming {endpoint} from {cursor.isoformat()}")

    filter_values: tuple[str | None, ...] = report.filter_values or (None,)
    if report.filter_values_from_playlists:
        filter_values = tuple(_playlist_ids(client, channel_id, resumable_source_manager))
        if not filter_values:
            logger.debug(f"YouTube Analytics: the channel owns no playlists, so {endpoint} has nothing to sync")
            resumable_source_manager.clear_state()
            return

    while cursor <= end_day:
        if report.day_is_dimension:
            window_end = min(cursor + timedelta(days=DAY_DIMENSION_WINDOW_DAYS - 1), end_day)
        else:
            window_end = cursor

        for filter_value in filter_values:
            rows = _fetch_window(client, report, ids, cursor, window_end, filter_value)
            if rows:
                yield rows
            else:
                # The staged cursor is this window's start, so a hand-off here re-reads only this window.
                resumable_source_manager.safe_point()

        cursor = window_end + timedelta(days=1)
        # Saved after the window is yielded: a crash re-yields the last window and the merge
        # on the day-keyed primary key dedupes it, rather than silently skipping days.
        resumable_source_manager.save_state(YouTubeAnalyticsResumeConfig(next_start_date=cursor.isoformat()))

    resumable_source_manager.clear_state()


def _uploads_playlist_id(client: YouTubeAnalyticsClient, channel_id: str | None) -> str | None:
    params = {"part": "contentDetails", "maxResults": "1"}
    cleaned = (channel_id or "").strip()
    if cleaned:
        params["id"] = cleaned
    else:
        params["mine"] = "true"
    body = client.get_json(f"{YOUTUBE_DATA_HOST}/channels?{urlencode(params)}")
    for item in body.get("items") or []:
        uploads = ((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
        if uploads:
            return uploads
    return None


def get_video_rows(
    access_token: str,
    refresh_access_token: AccessTokenRefresher | None,
    channel_id: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[YouTubeAnalyticsResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Every video in the channel's uploads playlist, with its metadata and lifetime statistics."""
    client = YouTubeAnalyticsClient(access_token, refresh_access_token=refresh_access_token, logger=logger)

    playlist_id = _uploads_playlist_id(client, channel_id)
    if playlist_id is None:
        logger.warning("YouTube Analytics: the channel has no uploads playlist, so no videos to sync")
        return

    seen: set[str] = set()
    page_token: str | None = None
    while True:
        params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": str(MAX_VIDEOS_PER_PAGE)}
        if page_token:
            params["pageToken"] = page_token
        try:
            page = client.get_json(f"{YOUTUBE_DATA_HOST}/playlistItems?{urlencode(params)}")
        except requests.HTTPError as e:
            # A channel that never uploaded has no readable uploads playlist.
            if page_token is None and e.response is not None and e.response.status_code == 404:
                return
            raise

        # A video uploaded mid-walk shifts the playlist, which can repeat a video on the next page.
        video_ids = []
        for item in page.get("items") or []:
            video_id = (item.get("contentDetails") or {}).get("videoId")
            if video_id and video_id not in seen:
                seen.add(video_id)
                video_ids.append(video_id)

        rows: list[dict[str, Any]] = []
        if video_ids:
            video_params = {"part": VIDEO_PARTS, "id": ",".join(video_ids), "maxResults": str(MAX_VIDEOS_PER_PAGE)}
            rows = client.get_json(f"{YOUTUBE_DATA_HOST}/videos?{urlencode(video_params)}").get("items") or []
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()

        page_token = page.get("nextPageToken")
        if not page_token:
            break


def get_per_video_rows(
    report: YouTubeAnalyticsVideoReportConfig,
    access_token: str,
    refresh_access_token: AccessTokenRefresher | None,
    channel_id: str | None,
    start_date: str | None,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[YouTubeAnalyticsResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """One report per video over the sync window, for the channel's top videos by views in that window."""
    client = YouTubeAnalyticsClient(
        access_token, refresh_access_token=refresh_access_token, api_version=api_version, logger=logger
    )
    today = datetime.now(UTC).date()
    end_day = today - timedelta(days=DATA_LATENCY_DAYS)
    start_day = resolve_start_day(start_date, False, None, today)
    if start_day > end_day:
        return

    window = {"ids": channel_ids_param(channel_id), "startDate": start_day.isoformat(), "endDate": end_day.isoformat()}
    top_videos_params = {
        **window,
        "dimensions": "video",
        "metrics": "views",
        "sort": "-views",
        "maxResults": str(MAX_PER_VIDEO_REPORT_VIDEOS),
    }
    if report.video_filter:
        top_videos_params["filters"] = report.video_filter
    top_videos = rows_from_result(client.query(top_videos_params))

    for video_id in [row.get("video") for row in top_videos]:
        if not video_id:
            continue
        # The report accepts exactly one video per request.
        rows = rows_from_result(
            client.query(
                {
                    **window,
                    "dimensions": report.dimension,
                    "metrics": ",".join(report.metrics),
                    "filters": f"video=={video_id}",
                }
            )
        )
        for row in rows:
            row["video"] = video_id
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()


def youtube_analytics_source(
    access_token: str,
    refresh_access_token: AccessTokenRefresher | None,
    channel_id: str | None,
    start_date: str | None,
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[YouTubeAnalyticsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    if endpoint == VIDEOS:
        return SourceResponse(
            name=endpoint,
            items=lambda: get_video_rows(
                access_token=access_token,
                refresh_access_token=refresh_access_token,
                channel_id=channel_id,
                logger=logger,
                resumable_source_manager=resumable_source_manager,
            ),
            primary_keys=FULL_REFRESH_PRIMARY_KEYS[VIDEOS],
        )

    if endpoint in PER_VIDEO_REPORTS:
        per_video_report = PER_VIDEO_REPORTS[endpoint]
        return SourceResponse(
            name=endpoint,
            items=lambda: get_per_video_rows(
                report=per_video_report,
                access_token=access_token,
                refresh_access_token=refresh_access_token,
                channel_id=channel_id,
                start_date=start_date,
                api_version=api_version,
                logger=logger,
                resumable_source_manager=resumable_source_manager,
            ),
            primary_keys=per_video_report.primary_keys,
        )

    report = YOUTUBE_ANALYTICS_REPORTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            refresh_access_token=refresh_access_token,
            channel_id=channel_id,
            start_date=start_date,
            endpoint=endpoint,
            api_version=api_version,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=report.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[DAY_FIELD],
        sort_mode="asc" if report.rows_ascend_by_day else None,
    )
