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
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.youtubeanalytics import (
    YouTubeAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.settings import (
    CHANNEL_DAILY,
    DEMOGRAPHICS,
    GEOGRAPHY,
    MAX_RESULTS_PER_PAGE,
    TOP_VIDEOS,
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


def _driver(start_date: str | None = None) -> SourceDriver:
    config = YouTubeAnalyticsSourceConfig(channel_id="", youtube_analytics_integration_id=1, start_date=start_date)
    return SourceDriver(YouTubeAnalyticsSource(), config)


def _result(headers: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"columnHeaders": [{"name": name} for name in headers], "rows": rows}


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
            (CHANNEL_DAILY, ["day"]),
            (TOP_VIDEOS, ["day", "video"]),
            (DEMOGRAPHICS, ["day", "ageGroup", "gender"]),
        ]
    )
    def test_primary_keys_are_unique_table_wide(self, endpoint: str, expected: list[str]) -> None:
        with _connected_account():
            response = _driver().run(endpoint, []).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected

    @time_machine.travel(FROZEN_NOW, tick=False)
    def test_items_is_lazy_until_iterated(self) -> None:
        with _connected_account():
            result = _driver(start_date="2026-07-25").run(
                GEOGRAPHY, [ScriptedResponse(json=_result(["country", "views"], [["US", 3]]))]
            )

        assert result.items == [[{"country": "US", "views": 3, "day": datetime(2026, 7, 25, tzinfo=UTC)}]]
