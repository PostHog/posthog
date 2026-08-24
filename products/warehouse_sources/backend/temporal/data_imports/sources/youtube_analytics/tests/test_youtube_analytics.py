from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.settings import (
    CHANNEL_DAILY,
    DEMOGRAPHICS,
    GEOGRAPHY,
    MAX_RESULTS_PER_PAGE,
    TOP_VIDEOS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.youtube_analytics import (
    YouTubeAnalyticsClient,
    YouTubeAnalyticsResumeConfig,
    channel_ids_param,
    coerce_day,
    get_rows,
    list_channels,
    resolve_start_day,
    rows_from_result,
    validate_credentials,
    youtube_analytics_source,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.youtube_analytics"
FROZEN_NOW = "2026-07-26"


class FakeResumeManager(ResumableSourceManager[YouTubeAnalyticsResumeConfig]):
    """In-memory stand-in for the Redis-backed manager."""

    def __init__(self, state: YouTubeAnalyticsResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[YouTubeAnalyticsResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> YouTubeAnalyticsResumeConfig | None:
        return self.state

    def save_state(self, data: YouTubeAnalyticsResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def _response(status: int = 200, json_body: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status
    response.ok = 200 <= status < 300
    response.text = text
    response.json.return_value = json_body if json_body is not None else {}
    response.raise_for_status.side_effect = (
        None if response.ok else requests.HTTPError(f"{status} Client Error", response=response)
    )
    return response


def _result(headers: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"columnHeaders": [{"name": name} for name in headers], "rows": rows}


def _run_get_rows(
    endpoint: str,
    query_results: list[dict[str, Any]],
    manager: FakeResumeManager,
    **overrides: Any,
) -> tuple[list[list[dict[str, Any]]], list[dict[str, str]]]:
    """Drive `get_rows` with a stubbed report client, returning yielded batches and sent params."""
    sent: list[dict[str, str]] = []

    def _query(params: dict[str, str]) -> dict[str, Any]:
        sent.append(params)
        return query_results[min(len(sent) - 1, len(query_results) - 1)]

    kwargs: dict[str, Any] = {
        "access_token": "access-token",
        "refresh_access_token": None,
        "channel_id": None,
        "start_date": None,
        "endpoint": endpoint,
        "api_version": "v2",
        "logger": mock.MagicMock(),
        "resumable_source_manager": manager,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
    }
    kwargs.update(overrides)

    with mock.patch.object(YouTubeAnalyticsClient, "query", side_effect=_query):
        with mock.patch(f"{MODULE}.make_tracked_session"):
            batches = list(get_rows(**kwargs))

    return batches, sent


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
    def test_zips_column_headers_onto_positional_rows(self) -> None:
        rows = rows_from_result(_result(["day", "views"], [["2026-07-01", 10], ["2026-07-02", 20]]))

        assert rows == [{"day": "2026-07-01", "views": 10}, {"day": "2026-07-02", "views": 20}]

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
    def _client(self, session: mock.MagicMock, **kwargs: Any) -> YouTubeAnalyticsClient:
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            return YouTubeAnalyticsClient("tok-1", logger=mock.MagicMock(), **kwargs)

    def test_requests_are_bearer_authorized_with_the_integration_token(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(json_body=_result(["views"], [[1]]))

        self._client(session).query({"ids": "channel==MINE"})

        assert session.get.call_args.kwargs["headers"] == {"Authorization": "Bearer tok-1"}

    def test_rejected_token_is_refreshed_once_and_the_request_retried(self) -> None:
        # A backfill can outlive Google's ~1h access token, so a mid-sync 401 must not fail the job.
        session = mock.MagicMock()
        session.get.side_effect = [_response(status=401), _response(json_body=_result(["views"], [[7]]))]
        refresh = mock.MagicMock(return_value="tok-2")

        body = self._client(session, refresh_access_token=refresh).query({"ids": "channel==MINE"})

        assert rows_from_result(body) == [{"views": 7}]
        assert refresh.call_count == 1
        assert session.get.call_args.kwargs["headers"] == {"Authorization": "Bearer tok-2"}

    def test_a_second_rejection_is_raised_rather_than_refreshed_again(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = [_response(status=401), _response(status=401)]
        refresh = mock.MagicMock(return_value="tok-2")

        with pytest.raises(requests.HTTPError):
            self._client(session, refresh_access_token=refresh).query({"ids": "channel==MINE"})

        assert refresh.call_count == 1

    def test_rejected_token_without_a_refresher_raises(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(status=401)

        with pytest.raises(requests.HTTPError):
            self._client(session).query({"ids": "channel==MINE"})

    @parameterized.expand([("forbidden", 403), ("bad_request", 400), ("server_error", 500)])
    def test_failed_report_request_raises(self, _name: str, status: int) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(status=status, text="nope")

        with pytest.raises(requests.HTTPError):
            self._client(session).query({"ids": "channel==MINE"})

    def test_reports_url_uses_the_resolved_api_version(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session"):
            client = YouTubeAnalyticsClient("tok", api_version="v3")

        assert client.reports_url == "https://youtubeanalytics.googleapis.com/v3/reports"

    def test_report_bodies_are_kept_out_of_diagnostic_capture(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as session_factory:
            YouTubeAnalyticsClient("tok")

        session_factory.assert_called_once_with(capture=False)


class TestListChannels:
    def _call(self, body: Any) -> tuple[list[dict[str, Any]], mock.MagicMock]:
        session = mock.MagicMock()
        session.get.return_value = _response(json_body=body)
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            return list_channels("tok"), session

    def test_lists_only_the_connected_accounts_own_channels(self) -> None:
        channels, session = self._call({"items": [{"id": "UC123", "snippet": {"title": "Acme"}}]})

        url = session.get.call_args.args[0]
        assert "mine=true" in url
        assert "part=snippet" in url
        assert channels == [{"id": "UC123", "snippet": {"title": "Acme"}}]

    @parameterized.expand([("no_items", {}), ("null_items", {"items": None}), ("empty_items", {"items": []})])
    def test_returns_empty_when_the_account_owns_no_channel(self, _name: str, body: Any) -> None:
        channels, _ = self._call(body)

        assert channels == []

    def test_channel_listings_are_kept_out_of_diagnostic_capture(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(json_body={"items": []})
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session) as session_factory:
            list_channels("tok")

        session_factory.assert_called_once_with(capture=False)


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


@freeze_time(FROZEN_NOW)
class TestGetRows:
    def test_day_dimension_report_covers_a_multi_day_window_per_request(self) -> None:
        manager = FakeResumeManager()
        result = _result(["day", "views"], [["2026-07-20", 5], ["2026-07-21", 6]])

        batches, sent = _run_get_rows(CHANNEL_DAILY, [result], manager, start_date="2026-01-01")

        # 2026-01-01 → 2026-07-25 is three 90-day windows.
        assert [(p["startDate"], p["endDate"]) for p in sent] == [
            ("2026-01-01", "2026-03-31"),
            ("2026-04-01", "2026-06-29"),
            ("2026-06-30", "2026-07-25"),
        ]
        assert sent[0]["dimensions"] == "day"
        assert sent[0]["sort"] == "day"
        # The report's own `day` column is parsed rather than stamped from the window start.
        assert batches[0][0]["day"] == datetime(2026, 7, 20, tzinfo=UTC)

    def test_aggregate_report_is_queried_one_day_at_a_time_and_stamped(self) -> None:
        manager = FakeResumeManager()
        result = _result(["ageGroup", "gender", "viewerPercentage"], [["age18-24", "female", 12.5]])

        batches, sent = _run_get_rows(DEMOGRAPHICS, [result], manager, start_date="2026-07-23")

        assert [(p["startDate"], p["endDate"]) for p in sent] == [
            ("2026-07-23", "2026-07-23"),
            ("2026-07-24", "2026-07-24"),
            ("2026-07-25", "2026-07-25"),
        ]
        assert sent[0]["dimensions"] == "ageGroup,gender"
        assert [batch[0]["day"] for batch in batches] == [
            datetime(2026, 7, 23, tzinfo=UTC),
            datetime(2026, 7, 24, tzinfo=UTC),
            datetime(2026, 7, 25, tzinfo=UTC),
        ]

    def test_stops_before_today_because_the_current_day_is_partial(self) -> None:
        manager = FakeResumeManager()
        _, sent = _run_get_rows(GEOGRAPHY, [_result(["country", "views"], [])], manager, start_date="2026-07-25")

        assert [p["endDate"] for p in sent] == ["2026-07-25"]

    def test_nothing_is_requested_when_the_start_day_is_in_the_future(self) -> None:
        manager = FakeResumeManager()
        batches, sent = _run_get_rows(GEOGRAPHY, [_result(["country"], [])], manager, start_date="2026-08-01")

        assert (batches, sent) == ([], [])

    def test_paginates_a_full_page_with_start_index(self) -> None:
        manager = FakeResumeManager()
        full_page = _result(["country", "views"], [["US", 1]] * MAX_RESULTS_PER_PAGE)
        short_page = _result(["country", "views"], [["FR", 2]])

        batches, sent = _run_get_rows(GEOGRAPHY, [full_page, short_page], manager, start_date="2026-07-25")

        assert [p["startIndex"] for p in sent] == ["1", str(MAX_RESULTS_PER_PAGE + 1)]
        assert len(batches[0]) == MAX_RESULTS_PER_PAGE + 1

    def test_top_n_report_takes_a_single_page(self) -> None:
        manager = FakeResumeManager()
        full_page = _result(["video", "views"], [["vid", 1]] * MAX_RESULTS_PER_PAGE)

        batches, sent = _run_get_rows(TOP_VIDEOS, [full_page], manager, start_date="2026-07-25")

        # YouTube caps `video`-keyed reports at 200 rows, so a full page is the end of the report.
        assert len(sent) == 1
        assert sent[0]["sort"] == "-estimatedMinutesWatched"
        assert len(batches[0]) == MAX_RESULTS_PER_PAGE

    def test_empty_windows_are_not_yielded(self) -> None:
        manager = FakeResumeManager()
        batches, sent = _run_get_rows(GEOGRAPHY, [_result(["country"], [])], manager, start_date="2026-07-23")

        assert batches == []
        assert len(sent) == 3

    def test_saves_resume_state_after_every_window_and_clears_on_completion(self) -> None:
        manager = FakeResumeManager()
        _run_get_rows(GEOGRAPHY, [_result(["country", "views"], [["US", 1]])], manager, start_date="2026-07-24")

        assert [state.next_start_date for state in manager.saved] == ["2026-07-25", "2026-07-26"]
        assert manager.cleared is True

    def test_resumes_from_saved_state_instead_of_the_configured_start(self) -> None:
        manager = FakeResumeManager(YouTubeAnalyticsResumeConfig(next_start_date="2026-07-25"))

        _, sent = _run_get_rows(GEOGRAPHY, [_result(["country"], [])], manager, start_date="2026-01-01")

        assert [p["startDate"] for p in sent] == ["2026-07-25"]

    def test_incremental_watermark_bounds_the_first_window(self) -> None:
        manager = FakeResumeManager()

        _, sent = _run_get_rows(
            GEOGRAPHY,
            [_result(["country"], [])],
            manager,
            start_date="2026-01-01",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 24, tzinfo=UTC),
        )

        assert [p["startDate"] for p in sent] == ["2026-07-24", "2026-07-25"]

    def test_channel_id_is_sent_as_the_ids_filter(self) -> None:
        manager = FakeResumeManager()

        _, sent = _run_get_rows(
            GEOGRAPHY, [_result(["country"], [])], manager, start_date="2026-07-25", channel_id="UC123"
        )

        assert sent[0]["ids"] == "channel==UC123"


@freeze_time(FROZEN_NOW)
class TestValidateCredentials:
    def _patch_client(self, query: Any) -> Any:
        client = mock.MagicMock(spec=YouTubeAnalyticsClient)
        client.query.side_effect = query
        return mock.patch(f"{MODULE}.YouTubeAnalyticsClient", return_value=client)

    def test_valid_credentials(self) -> None:
        with self._patch_client(query=[{"columnHeaders": [], "rows": []}]):
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
        error = requests.HTTPError("boom", response=_response(status=status))

        with self._patch_client(query=error):
            is_valid, message = validate_credentials("access-token", "UC123")

        assert is_valid is False
        assert message is not None and fragment in message

    def test_network_failure_is_reported_not_raised(self) -> None:
        with self._patch_client(query=requests.ConnectionError("no route")):
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
        # A bad start date is caught before any API call, so no request is made.
        is_valid, message = validate_credentials("access-token", "UC123", start_date=start_date)

        assert is_valid is False
        assert message is not None and fragment in message


class TestYouTubeAnalyticsSourceResponse:
    @parameterized.expand(
        [
            (CHANNEL_DAILY, ["day"]),
            (TOP_VIDEOS, ["day", "video"]),
            (DEMOGRAPHICS, ["day", "ageGroup", "gender"]),
        ]
    )
    def test_primary_keys_are_unique_table_wide(self, endpoint: str, expected: list[str]) -> None:
        response = youtube_analytics_source(
            access_token="access-token",
            refresh_access_token=None,
            channel_id=None,
            start_date=None,
            endpoint=endpoint,
            api_version="v2",
            logger=mock.MagicMock(),
            resumable_source_manager=FakeResumeManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == expected

    def test_partitions_and_sorts_on_the_day_column(self) -> None:
        response = youtube_analytics_source(
            access_token="access-token",
            refresh_access_token=None,
            channel_id=None,
            start_date=None,
            endpoint=GEOGRAPHY,
            api_version="v2",
            logger=mock.MagicMock(),
            resumable_source_manager=FakeResumeManager(),
        )

        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["day"]
        # Windows are walked oldest-first, so the incremental watermark advances safely.
        assert response.sort_mode == "asc"

    @freeze_time(FROZEN_NOW)
    def test_items_is_lazy_until_iterated(self) -> None:
        manager = FakeResumeManager()
        response = youtube_analytics_source(
            access_token="access-token",
            refresh_access_token=None,
            channel_id=None,
            start_date="2026-07-25",
            endpoint=GEOGRAPHY,
            api_version="v2",
            logger=mock.MagicMock(),
            resumable_source_manager=manager,
        )

        with mock.patch.object(
            YouTubeAnalyticsClient, "query", return_value=_result(["country", "views"], [["US", 3]])
        ):
            with mock.patch(f"{MODULE}.make_tracked_session"):
                batches = list(cast("Iterable[Any]", response.items()))

        assert batches == [[{"country": "US", "views": 3, "day": datetime(2026, 7, 25, tzinfo=UTC)}]]
