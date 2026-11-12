from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.wistia._config import WistiaSourceConfig
from products.warehouse_sources.sources.wistia.source import WistiaSource
from products.warehouse_sources.sources.wistia.wistia import WistiaResumeConfig, validate_credentials

TODAY = "2026-11-12T08:00:00Z"


@pytest.fixture(autouse=True)
def _frozen_clock():
    with time_machine.travel(TODAY, tick=False):
        yield


def _driver() -> SourceDriver:
    return SourceDriver(WistiaSource(), WistiaSourceConfig(api_token="tok"))


def _page(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json=rows)


def _medias(count: int, start: int = 0) -> list[dict[str, Any]]:
    return [{"hashed_id": f"m{i}", "created": "2026-01-01T00:00:00Z", "cursor": f"c{i}"} for i in range(start, count)]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid_token", 200, True, None),
            ("wrong_token", 401, False, "Wistia rejected the API token"),
            ("server_error", 500, False, "status 500"),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool, expected_message: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            ok, message = validate_credentials("tok", "2026-09")

        assert ok is expected_ok
        assert message is None if expected_message is None else expected_message in (message or "")
        assert {request.path for request in network.requests_log} == {"/modern/account"}
        assert {request.headers["x-wistia-api-version"] for request in network.requests_log} == {"2026-09"}
        assert {request.headers["authorization"] for request in network.requests_log} == {"Bearer tok"}

    def test_network_error_is_not_reported_as_a_wrong_token(self) -> None:
        with scripted_network(always(requests.ConnectionError("connection reset"))):
            ok, message = validate_credentials("tok", "2026-09")

        assert ok is False
        assert message is not None and "Couldn't reach Wistia" in message


class TestTopLevelPagination:
    def test_walks_pages_until_a_short_page(self) -> None:
        result = _driver().run("medias", [_page(_medias(100)), _page(_medias(101, start=100))])

        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert result.params("per_page") == ["100", "100"]
        assert result.params("sort_by") == ["created", "created"]
        assert result.paths == ["/modern/medias", "/modern/medias"]
        assert {request.headers["x-wistia-api-version"] for request in result.requests} == {"2026-09"}
        assert {request.headers["authorization"] for request in result.requests} == {"Bearer tok"}
        assert len(result.rows) == 101
        assert all("cursor" not in row for row in result.rows)
        assert result.saved_states == [WistiaResumeConfig(page=2)]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run("medias", [_page(_medias(1))], resume_state=WistiaResumeConfig(page=3))

        assert result.raised is None
        assert result.params("page") == ["3"]
        assert [row["hashed_id"] for row in result.rows] == ["m0"]

    @parameterized.expand(
        [
            ("events_incremental_datetime", "events", True, datetime(2026, 3, 4, 23, 30, tzinfo=UTC), "2026-03-04"),
            ("events_incremental_iso_string", "events", True, "2026-03-04T02:00:00Z", "2026-03-04"),
            ("events_full_refresh", "events", False, None, None),
            ("full_refresh_endpoint_ignores_watermark", "visitors", True, datetime(2026, 3, 4, tzinfo=UTC), None),
        ]
    )
    def test_start_date_filter(
        self, _name: str, endpoint: str, incremental: bool, last_value: Any, expected_start: str | None
    ) -> None:
        kwargs: dict[str, Any] = (
            {"incremental_field": "received_at", "db_incremental_field_last_value": last_value}
            if incremental
            else {"should_use_incremental_field": False}
        )
        result = _driver().run(endpoint, [_page([])], **kwargs)

        assert result.raised is None
        assert result.params("start_date") == [expected_start]

    def test_unauthorized_response_fails_the_sync(self) -> None:
        result = _driver().run(
            "tags",
            [ScriptedResponse(status=401, json={"code": "unauthorized_scope", "error": "Invalid credentials."})],
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert "401 Client Error: Unauthorized" in str(result.raised)


class TestFanOut:
    def test_subfolders_carry_the_folder_id_and_skip_a_deleted_folder(self) -> None:
        result = _driver().run(
            "subfolders",
            [
                _page([{"hashed_id": "f1"}, {"hashed_id": "f2"}, {"hashed_id": "f3"}]),
                _page([{"hashed_id": "s1", "name": "A", "cursor": "x"}]),
                ScriptedResponse(status=404, json={"error": "Folder not found"}),
                _page([{"hashed_id": "s1", "name": "B"}]),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/modern/folders",
            "/modern/folders/f1/subfolders",
            "/modern/folders/f2/subfolders",
            "/modern/folders/f3/subfolders",
        ]
        assert result.requests[1].param("page") == "1"
        assert result.requests[1].param("per_page") == "100"
        # The same subfolder id in two folders stays two rows, keyed by the folder id.
        assert result.rows == [
            {"hashed_id": "s1", "name": "A", "folder_hashed_id": "f1"},
            {"hashed_id": "s1", "name": "B", "folder_hashed_id": "f3"},
        ]

    def test_subfolders_follow_child_pages(self) -> None:
        subfolders = [{"hashed_id": f"s{i}"} for i in range(100)]
        result = _driver().run(
            "subfolders",
            [_page([{"hashed_id": "f1"}]), _page(subfolders), _page([{"hashed_id": "s100"}])],
        )

        assert result.raised is None
        assert [request.param("page") for request in result.requests[1:]] == ["1", "2"]
        assert len(result.rows) == 101

    def test_media_stats_reads_one_object_per_media(self) -> None:
        result = _driver().run(
            "media_stats",
            [
                _page([{"hashed_id": "m1"}, {"hashed_id": "m2"}]),
                ScriptedResponse(json={"load_count": 10, "play_count": 4, "actions": []}),
                ScriptedResponse(json={"load_count": 3, "play_count": 1, "actions": []}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/modern/medias", "/modern/stats/medias/m1", "/modern/stats/medias/m2"]
        assert result.requests[1].param("page") is None
        assert result.rows == [
            {"load_count": 10, "play_count": 4, "actions": [], "media_hashed_id": "m1"},
            {"load_count": 3, "play_count": 1, "actions": [], "media_hashed_id": "m2"},
        ]

    def test_resume_skips_completed_parents(self) -> None:
        result = _driver().run(
            "media_stats",
            [_page([{"hashed_id": "m1"}, {"hashed_id": "m2"}]), ScriptedResponse(json={"load_count": 1})],
            resume_state=WistiaResumeConfig(
                fanout_state={"completed": ["/stats/medias/m1"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.paths == ["/modern/medias", "/modern/stats/medias/m2"]
        assert result.rows == [{"load_count": 1, "media_hashed_id": "m2"}]


def _account_stats_answer(request: RecordedRequest) -> ScriptedResponse:
    start = request.param("start_date")
    if start == "2010-01-01":
        return _page([])
    return _page([{"date": start, "load_count": 1, "play_count": 1, "hours_watched": 0.5}])


class TestAccountStatsByDate:
    @parameterized.expand(
        [
            (
                "incremental_rereads_the_watermark_day",
                date(2025, 1, 1),
                [("2025-01-01", "2025-12-31"), ("2026-01-01", "2026-11-12")],
            ),
            ("incremental_from_today", datetime(2026, 11, 12, 6, 0, tzinfo=UTC), [("2026-11-12", "2026-11-12")]),
        ]
    )
    def test_incremental_windows(self, _name: str, last_value: Any, expected: list[tuple[str, str]]) -> None:
        result = _driver().run(
            "account_stats_by_date",
            _account_stats_answer,
            incremental_field="date",
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert set(result.paths) == {"/modern/stats/account/by_date"}
        assert list(zip(result.params("start_date"), result.params("end_date"))) == expected
        assert [row["date"] for row in result.rows] == [start for start, _ in expected]

    def test_full_refresh_walks_the_whole_history_in_yearly_windows(self) -> None:
        result = _driver().run("account_stats_by_date", _account_stats_answer, should_use_incremental_field=False)

        assert result.raised is None
        windows = list(zip(result.params("start_date"), result.params("end_date")))
        assert windows[0] == ("2010-01-01", "2010-12-31")
        assert windows[-1][1] == "2026-11-12"
        # Windows are contiguous: each starts the day after the previous one ends.
        for (_, previous_end), (next_start, _) in zip(windows, windows[1:]):
            assert date.fromisoformat(next_start).toordinal() == date.fromisoformat(previous_end).toordinal() + 1
        # The empty first window yields nothing, every later window yields its row.
        assert len(result.rows) == len(windows) - 1

    def test_stages_the_next_window_before_each_yield_and_resumes_from_it(self) -> None:
        first = _driver().run(
            "account_stats_by_date",
            _account_stats_answer,
            incremental_field="date",
            db_incremental_field_last_value=date(2025, 1, 1),
        )
        assert first.committed_states == [
            WistiaResumeConfig(window_start="2026-01-01"),
            WistiaResumeConfig(window_start="2026-11-13"),
        ]

        resumed = _driver().run(
            "account_stats_by_date",
            _account_stats_answer,
            incremental_field="date",
            db_incremental_field_last_value=date(2025, 1, 1),
            resume_state=WistiaResumeConfig(window_start="2026-01-01"),
        )
        assert resumed.raised is None
        assert resumed.params("start_date") == ["2026-01-01"]
