import contextlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.youtubeanalytics import (
    YouTubeAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.settings import (
    AUDIENCE_RETENTION,
    CHANNEL_DAILY,
    CONCURRENT_VIEWERS,
    DEMOGRAPHICS,
    GEOGRAPHY,
    MAX_RESULTS_PER_PAGE,
    PLAYLIST_DAILY,
    TOP_VIDEOS,
    TRAFFIC_SOURCE_DETAILS,
    VIDEOS,
    YOUTUBE_ANALYTICS_REPORTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.source import (
    YouTubeAnalyticsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.youtube_analytics import (
    YouTubeAnalyticsClient,
    YouTubeAnalyticsResumeConfig,
    channel_ids_param,
    coerce_day,
    list_channels,
    resolve_start_day,
    rows_from_result,
    validate_credentials,
)

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.source"
FROZEN_NOW = "2026-07-26"


@contextlib.contextmanager
def _connected_account() -> Iterator[None]:
    """Stand in for the DB-backed integration that holds the Google access token."""
    integration = mock.MagicMock()
    integration.access_token = "access-token"
    integration.errors = ""
    oauth = mock.MagicMock()
    oauth.access_token_expired.return_value = False
    with (
        mock.patch.object(YouTubeAnalyticsSource, "get_oauth_integration", return_value=integration),
        mock.patch(f"{SOURCE_MODULE}.OauthIntegration", return_value=oauth),
    ):
        yield


def _driver(start_date: str | None = None, channel_id: str = "") -> SourceDriver:
    config = YouTubeAnalyticsSourceConfig(
        channel_id=channel_id, youtube_analytics_integration_id=1, start_date=start_date
    )
    return SourceDriver(YouTubeAnalyticsSource(), config)


def _result(headers: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"columnHeaders": [{"name": name} for name in headers], "rows": rows}


def _channel(uploads: str | None = "UU123") -> ScriptedResponse:
    items = [{"id": "UC123", "contentDetails": {"relatedPlaylists": {"uploads": uploads}}}] if uploads else []
    return ScriptedResponse(json={"items": items})


def _playlist_page(video_ids: list[str], next_page_token: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"items": [{"contentDetails": {"videoId": video_id}} for video_id in video_ids]}
    if next_page_token:
        body["nextPageToken"] = next_page_token
    return ScriptedResponse(json=body)


def _playlists(playlist_ids: list[str], next_page_token: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"items": [{"id": playlist_id} for playlist_id in playlist_ids]}
    if next_page_token:
        body["nextPageToken"] = next_page_token
    return ScriptedResponse(json=body)


def _videos(video_ids: list[str]) -> ScriptedResponse:
    return ScriptedResponse(
        json={"items": [{"id": video_id, "snippet": {"title": f"Video {video_id}"}} for video_id in video_ids]}
    )


class TestChannelIdsParam:
    @parameterized.expand(
        [
            ("blank", None, "channel==MINE"),
            ("empty_string", "", "channel==MINE"),
            ("whitespace", "   ", "channel==MINE"),
            ("explicit", "UC_x5XG1OV2P6uZZ5FSM9Ttw", "channel==UC_x5XG1OV2P6uZZ5FSM9Ttw"),
            ("padded", " UC123 ", "channel==UC123"),
        ]
    )
    def test_builds_ids_filter(self, _name: str, channel_id: str | None, expected: str) -> None:
        assert channel_ids_param(channel_id) == expected


class TestCoerceDay:
    @parameterized.expand(
        [
            ("iso_string", "2026-07-04", datetime(2026, 7, 4, tzinfo=UTC)),
            ("iso_datetime_string", "2026-07-04T13:00:00+00:00", datetime(2026, 7, 4, tzinfo=UTC)),
            ("date", date(2026, 7, 4), datetime(2026, 7, 4, tzinfo=UTC)),
            ("naive_datetime", datetime(2026, 7, 4, 5, 30), datetime(2026, 7, 4, 5, 30, tzinfo=UTC)),
            ("aware_datetime", datetime(2026, 7, 4, tzinfo=UTC), datetime(2026, 7, 4, tzinfo=UTC)),
        ]
    )
    def test_normalizes_to_utc(self, _name: str, value: Any, expected: datetime) -> None:
        assert coerce_day(value) == expected

    @parameterized.expand([("none", None), ("empty", ""), ("garbage", "not-a-date"), ("number", 20260704)])
    def test_returns_none_for_unusable(self, _name: str, value: Any) -> None:
        assert coerce_day(value) is None


class TestRowsFromResult:
    @parameterized.expand(
        [
            ("no_rows", {"columnHeaders": [{"name": "views"}]}),
            ("no_headers", {"rows": [[1]]}),
            ("empty_body", {}),
        ]
    )
    def test_returns_empty_when_nothing_to_map(self, _name: str, body: dict[str, Any]) -> None:
        assert rows_from_result(body) == []


class TestYouTubeAnalyticsClient:
    def test_rejected_token_is_refreshed_once_and_the_request_retried(self) -> None:
        # A backfill can outlive Google's ~1h access token, so a mid-sync 401 must not fail the job.
        refresh = mock.MagicMock(return_value="tok-2")
        script = [ScriptedResponse(status=401), ScriptedResponse(json=_result(["views"], [[7]]))]

        with scripted_network(script) as network:
            client = YouTubeAnalyticsClient("tok-1", logger=mock.MagicMock(), refresh_access_token=refresh)
            body = client.query({"ids": "channel==MINE"})

        assert rows_from_result(body) == [{"views": 7}]
        assert refresh.call_count == 1
        assert [request.headers["authorization"] for request in network.requests_log] == [
            "Bearer tok-1",
            "Bearer tok-2",
        ]

    def test_a_second_rejection_is_raised_rather_than_refreshed_again(self) -> None:
        refresh = mock.MagicMock(return_value="tok-2")

        with scripted_network([ScriptedResponse(status=401), ScriptedResponse(status=401)]):
            client = YouTubeAnalyticsClient("tok-1", logger=mock.MagicMock(), refresh_access_token=refresh)
            with pytest.raises(requests.HTTPError):
                client.query({"ids": "channel==MINE"})

        assert refresh.call_count == 1

    def test_rejected_token_without_a_refresher_raises(self) -> None:
        with scripted_network(always(ScriptedResponse(status=401))):
            client = YouTubeAnalyticsClient("tok-1", logger=mock.MagicMock())
            with pytest.raises(requests.HTTPError):
                client.query({"ids": "channel==MINE"})

    @parameterized.expand([("forbidden", 403), ("bad_request", 400), ("server_error", 500)])
    def test_failed_report_request_raises(self, _name: str, status: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status, body=b"nope"))):
            client = YouTubeAnalyticsClient("tok-1", logger=mock.MagicMock())
            with pytest.raises(requests.HTTPError):
                client.query({"ids": "channel==MINE"})


class TestListChannels:
    @parameterized.expand([("no_items", {}), ("null_items", {"items": None}), ("empty_items", {"items": []})])
    def test_returns_empty_when_the_account_owns_no_channel(self, _name: str, body: Any) -> None:
        with scripted_network([ScriptedResponse(json=body)]):
            assert list_channels("tok") == []


class TestResolveStartDay:
    @parameterized.expand(
        [
            ("default_lookback", None, False, None, date(2025, 7, 26)),
            ("pinned_start_date", "2026-01-15", False, None, date(2026, 1, 15)),
            ("watermark_wins", "2026-01-15", True, "2026-06-01", date(2026, 6, 1)),
            ("watermark_before_floor_is_clamped", "2026-06-01", True, "2026-01-15", date(2026, 6, 1)),
            ("watermark_ignored_on_full_refresh", "2026-01-15", False, "2026-06-01", date(2026, 1, 15)),
            ("unparseable_watermark_falls_back", "2026-01-15", True, "garbage", date(2026, 1, 15)),
            ("start_before_floor_is_clamped", "2000-01-01", False, None, date(2008, 1, 1)),
        ]
    )
    def test_resolves_first_day(
        self,
        _name: str,
        start_date: str | None,
        should_use_incremental_field: bool,
        last_value: Any,
        expected: date,
    ) -> None:
        assert resolve_start_day(start_date, should_use_incremental_field, last_value, date(2026, 7, 26)) == expected


class TestGetRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel(FROZEN_NOW, tick=False):
            yield

    @pytest.fixture(autouse=True)
    def _account(self):
        with _connected_account():
            yield

    def test_day_dimension_report_covers_a_multi_day_window_per_request(self) -> None:
        result = _driver(start_date="2026-01-01").run(
            CHANNEL_DAILY,
            always(ScriptedResponse(json=_result(["day", "views"], [["2026-07-20", 5], ["2026-07-21", 6]]))),
        )

        # 2026-01-01 → 2026-07-25 is three 90-day windows.
        assert [(r.param("startDate"), r.param("endDate")) for r in result.requests] == [
            ("2026-01-01", "2026-03-31"),
            ("2026-04-01", "2026-06-29"),
            ("2026-06-30", "2026-07-25"),
        ]
        assert result.requests[0].param("dimensions") == "day"
        assert result.requests[0].param("sort") == "day"
        # The report's own `day` column is parsed rather than stamped from the window start.
        assert result.items[0][0]["day"] == datetime(2026, 7, 20, tzinfo=UTC)

    def test_paginates_a_full_page_with_start_index(self) -> None:
        full_page = _result(["country", "views"], [["US", 1]] * MAX_RESULTS_PER_PAGE)
        short_page = _result(["country", "views"], [["FR", 2]])

        result = _driver(start_date="2026-07-25").run(
            GEOGRAPHY, [ScriptedResponse(json=full_page), ScriptedResponse(json=short_page)]
        )

        assert result.params("startIndex") == ["1", str(MAX_RESULTS_PER_PAGE + 1)]
        assert len(result.items[0]) == MAX_RESULTS_PER_PAGE + 1

    @parameterized.expand(
        [
            ("with_referrers", [["example.com", 4]], 9),
            ("no_referrers", [], 0),
        ]
    )
    def test_traffic_source_details_queries_each_traffic_source_type_per_day(
        self, _name: str, rows: list[list[Any]], expected_batches: int
    ) -> None:
        report = YOUTUBE_ANALYTICS_REPORTS[TRAFFIC_SOURCE_DETAILS]

        result = _driver(start_date="2026-07-24").run(
            TRAFFIC_SOURCE_DETAILS,
            always(ScriptedResponse(json=_result(["insightTrafficSourceDetail", "views"], rows))),
        )

        assert result.raised is None
        # The report rejects a request without exactly one traffic source type, a sort, or a cap of 25.
        assert result.params("filters") == [f"insightTrafficSourceType=={value}" for value in report.filter_values] * 2
        assert result.params("startDate") == ["2026-07-24"] * 9 + ["2026-07-25"] * 9
        assert set(result.params("sort")) == {"-views"}
        assert set(result.params("maxResults")) == {"25"}
        assert set(result.params("dimensions")) == {"insightTrafficSourceDetail"}
        assert len(result.items) == expected_batches * 2
        if rows:
            assert result.items[0] == [
                {
                    "insightTrafficSourceDetail": "example.com",
                    "views": 4,
                    "insightTrafficSourceType": "ADVERTISING",
                    "day": datetime(2026, 7, 24, tzinfo=UTC),
                }
            ]

    @parameterized.expand([("pinned_channel", "UC123", "id", "UC123"), ("blank_channel", "", "mine", "true")])
    def test_videos_walks_the_uploads_playlist_and_resolves_each_page(
        self, _name: str, channel_id: str, channel_param: str, channel_value: str
    ) -> None:
        script = route(
            {
                "/channels": [_channel()],
                "/playlistItems": [
                    _playlist_page(["vid-a", "vid-b"], next_page_token="page-2"),
                    # A video uploaded mid-walk pushes vid-b onto the next page as well.
                    _playlist_page(["vid-b", "vid-c"]),
                ],
                "/videos": [_videos(["vid-a", "vid-b"]), _videos(["vid-c"])],
            }
        )

        result = _driver(channel_id=channel_id).run(VIDEOS, script)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["vid-a", "vid-b", "vid-c"]
        channel_request, *rest = result.requests
        assert channel_request.param(channel_param) == channel_value
        assert [(r.path.rsplit("/", 1)[-1], r.param("pageToken"), r.param("id")) for r in rest] == [
            ("playlistItems", None, None),
            ("videos", None, "vid-a,vid-b"),
            ("playlistItems", "page-2", None),
            ("videos", None, "vid-c"),
        ]
        assert {r.param("playlistId") for r in rest if r.path.endswith("playlistItems")} == {"UU123"}

    @parameterized.expand(
        [
            ("channel_not_found", {"/channels": [_channel(uploads=None)]}, 1),
            ("never_uploaded", {"/channels": [_channel()], "/playlistItems": [ScriptedResponse(status=404)]}, 2),
            ("empty_playlist", {"/channels": [_channel()], "/playlistItems": [_playlist_page([])]}, 2),
        ]
    )
    def test_videos_syncs_nothing_for_a_channel_without_uploads(
        self, _name: str, table: dict[str, list[ScriptedResponse]], expected_requests: int
    ) -> None:
        result = _driver().run(VIDEOS, route(table))

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == expected_requests

    def test_videos_raises_when_a_later_playlist_page_is_missing(self) -> None:
        # Only a first-page 404 means "no uploads"; a later one would silently truncate the table.
        script = route(
            {
                "/channels": [_channel()],
                "/playlistItems": [_playlist_page(["vid-a"], next_page_token="page-2"), ScriptedResponse(status=404)],
                "/videos": [_videos(["vid-a"])],
            }
        )

        result = _driver().run(VIDEOS, script)

        assert isinstance(result.raised, requests.HTTPError)

    @parameterized.expand(
        [
            (AUDIENCE_RETENTION, "elapsedVideoTimeRatio", "audienceWatchRatio", None),
            # Without the live filter the top videos would be on-demand uploads that have no live curve.
            (CONCURRENT_VIEWERS, "livestreamPosition", "peakConcurrentViewers", "liveOrOnDemand==LIVE"),
        ]
    )
    def test_per_video_report_fetches_one_report_per_top_video(
        self, endpoint: str, dimension: str, metric: str, top_videos_filter: str | None
    ) -> None:
        script = [
            ScriptedResponse(json=_result(["video", "views"], [["vid-a", 10], ["vid-b", 5]])),
            ScriptedResponse(json=_result([dimension, metric], [[1, 120], [2, 90]])),
            ScriptedResponse(json=_result([dimension, metric], [])),
        ]

        result = _driver(start_date="2026-07-01").run(
            endpoint, script, should_use_incremental_field=True, db_incremental_field_last_value="2026-07-20"
        )

        assert result.raised is None
        assert result.params("filters") == [top_videos_filter, "video==vid-a", "video==vid-b"]
        assert result.params("dimensions") == ["video", dimension, dimension]
        # A per-video report covers the whole sync window, never a watermark slice of it.
        assert set(result.params("startDate")) == {"2026-07-01"}
        assert set(result.params("endDate")) == {"2026-07-25"}
        assert result.rows == [
            {dimension: 1, metric: 120, "video": "vid-a"},
            {dimension: 2, metric: 90, "video": "vid-a"},
        ]

    @parameterized.expand([("pinned_channel", "UC123", "channelId", "UC123"), ("blank_channel", "", "mine", "true")])
    def test_playlist_daily_queries_each_owned_playlist_per_window(
        self, _name: str, channel_id: str, channel_param: str, channel_value: str
    ) -> None:
        script = route(
            {
                "/playlists": [
                    _playlists(["PL-a", "PL-b"], next_page_token="page-2"),
                    # A playlist created mid-walk pushes PL-b onto the next page as well.
                    _playlists(["PL-b"]),
                ],
                "/reports": [
                    ScriptedResponse(json=_result(["day", "playlistStarts"], [["2026-07-24", 3], ["2026-07-25", 4]])),
                    ScriptedResponse(json=_result(["day", "playlistStarts"], [])),
                ],
            }
        )

        result = _driver(start_date="2026-07-24", channel_id=channel_id).run(PLAYLIST_DAILY, script)

        assert result.raised is None
        playlist_requests = [r for r in result.requests if r.path.endswith("/playlists")]
        assert [(r.param(channel_param), r.param("pageToken")) for r in playlist_requests] == [
            (channel_value, None),
            (channel_value, "page-2"),
        ]
        # The report rejects a request without exactly one playlist.
        assert result.params("filters") == [None, None, "playlist==PL-a", "playlist==PL-b"]
        assert set(result.params("dimensions")) == {None, "day"}
        assert result.rows == [
            {"day": datetime(2026, 7, 24, tzinfo=UTC), "playlistStarts": 3, "playlist": "PL-a"},
            {"day": datetime(2026, 7, 25, tzinfo=UTC), "playlistStarts": 4, "playlist": "PL-a"},
        ]

    def test_playlist_daily_sends_no_report_request_for_a_channel_without_playlists(self) -> None:
        result = _driver(start_date="2026-01-01").run(PLAYLIST_DAILY, route({"/playlists": [_playlists([])]}))

        assert result.raised is None
        assert result.rows == []
        assert [r.path.rsplit("/", 1)[-1] for r in result.requests] == ["playlists"]

    def test_resumes_from_saved_state_instead_of_the_configured_start(self) -> None:
        result = _driver(start_date="2026-01-01").run(
            GEOGRAPHY,
            always(ScriptedResponse(json=_result(["country"], []))),
            resume_state=YouTubeAnalyticsResumeConfig(next_start_date="2026-07-25"),
        )

        assert result.params("startDate") == ["2026-07-25"]


class TestValidateCredentials:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel(FROZEN_NOW, tick=False):
            yield

    def test_valid_credentials(self) -> None:
        with scripted_network([ScriptedResponse(json={"columnHeaders": [], "rows": []})]):
            assert validate_credentials("access-token", "UC123") == (True, None)

    @parameterized.expand(
        [
            ("unauthorized", 401, "reconnect"),
            ("forbidden", 403, "cannot read this channel"),
            ("bad_channel", 400, "Pick a channel"),
            ("unexpected", 500, "status 500"),
        ]
    )
    def test_report_errors_map_to_actionable_messages(self, _name: str, status: int, fragment: str) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            is_valid, message = validate_credentials("access-token", "UC123")

        assert is_valid is False
        assert message is not None and fragment in message

    def test_network_failure_is_reported_not_raised(self) -> None:
        with scripted_network(always(requests.ConnectionError("no route"))):
            is_valid, message = validate_credentials("access-token", "UC123")

        assert is_valid is False
        assert message is not None and "Could not reach" in message

    @parameterized.expand(
        [
            ("before_floor", "2000-01-01", "on or after 2008-01-01"),
            ("in_the_future", "2027-01-01", "can't be in the future"),
            ("unparseable", "not-a-date", "Invalid start date"),
        ]
    )
    def test_out_of_range_start_date_is_rejected_before_any_request(
        self, _name: str, start_date: str, fragment: str
    ) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("access-token", "UC123", start_date=start_date)

        assert network.requests_log == []
        assert is_valid is False
        assert message is not None and fragment in message


class TestYouTubeAnalyticsSourceResponse:
    @parameterized.expand(
        [
            (CHANNEL_DAILY, ["day"], "asc"),
            (TOP_VIDEOS, ["day", "video"], "asc"),
            (DEMOGRAPHICS, ["day", "ageGroup", "gender"], "asc"),
            (TRAFFIC_SOURCE_DETAILS, ["day", "insightTrafficSourceType", "insightTrafficSourceDetail"], "asc"),
            # Each playlist restarts at the first day of the 90-day window, so the rows are not in day order.
            (PLAYLIST_DAILY, ["day", "playlist"], None),
            (VIDEOS, ["id"], None),
            (AUDIENCE_RETENTION, ["video", "elapsedVideoTimeRatio"], None),
            (CONCURRENT_VIEWERS, ["video", "livestreamPosition"], None),
        ]
    )
    def test_primary_keys_are_unique_table_wide(
        self, endpoint: str, expected: list[str], sort_mode: str | None
    ) -> None:
        with _connected_account():
            response = _driver().run(endpoint, []).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected
        assert response.sort_mode == sort_mode

    @time_machine.travel(FROZEN_NOW, tick=False)
    def test_items_is_lazy_until_iterated(self) -> None:
        with _connected_account():
            result = _driver(start_date="2026-07-25").run(
                GEOGRAPHY, [ScriptedResponse(json=_result(["country", "views"], [["US", 3]]))]
            )

        assert result.items == [[{"country": "US", "views": 3, "day": datetime(2026, 7, 25, tzinfo=UTC)}]]
