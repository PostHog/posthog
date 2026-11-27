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

    def test_webinar_rows_drop_the_private_access_links(self) -> None:
        webinar = {
            "hashed_id": "w1",
            "audience_link": "https://example.com/join",
            "host_link": "https://example.com/host-secret",
            "panelist_link": "https://example.com/panelist-secret",
        }
        result = _driver().run("webinars", [_page([webinar])])

        assert result.raised is None
        assert result.rows == [{"hashed_id": "w1", "audience_link": "https://example.com/join"}]

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

    def test_checkpoint_keeps_only_the_last_two_parent_pages(self) -> None:
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/modern/medias":
                page = int(request.param("page") or 0)
                return _page([{"hashed_id": f"m{page}_{i}"} for i in range(100 if page < 4 else 1)])
            return ScriptedResponse(json={"load_count": 1})

        result = _driver().run("media_stats", answer)

        assert result.raised is None
        assert len(result.rows) == 301
        assert max(len(state.fanout_state["completed"]) for state in result.saved_states if state.fanout_state) == 200
        final_state = result.saved_states[-1].fanout_state
        assert final_state is not None and final_state["parent"] == {"page": 3}

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
            assert next_start is not None and previous_end is not None
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


class TestWebinarRegistrations:
    def test_follows_page_info_until_has_next_page_is_false(self) -> None:
        def registrations(keys: list[str], has_next: bool, end_cursor: str | None) -> ScriptedResponse:
            return ScriptedResponse(
                json={
                    "registrations": [{"visitor_key": key, "email": f"{key}@example.com"} for key in keys],
                    "page_info": {"has_next_page": has_next, "end_cursor": end_cursor},
                }
            )

        result = _driver().run(
            "webinar_registrations",
            [
                _page([{"hashed_id": "w1"}, {"hashed_id": "w2"}]),
                registrations(["v1"], True, "next-1"),
                # The last page still carries an end cursor; `has_next_page` ends the walk.
                registrations(["v2"], False, "last-cursor"),
                registrations(["v1"], False, None),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/modern/webinars",
            "/modern/webinars/w1/registrations",
            "/modern/webinars/w1/registrations",
            "/modern/webinars/w2/registrations",
        ]
        assert [request.param("cursor") for request in result.requests[1:]] == [None, "next-1", None]
        assert [(row["webinar_hashed_id"], row["visitor_key"]) for row in result.rows] == [
            ("w1", "v1"),
            ("w1", "v2"),
            ("w2", "v1"),
        ]

    def test_a_cursor_that_does_not_advance_fails_the_sync(self) -> None:
        stuck = ScriptedResponse(
            json={"registrations": [{"visitor_key": "v1"}], "page_info": {"has_next_page": True, "end_cursor": "same"}}
        )
        result = _driver().run("webinar_registrations", [_page([{"hashed_id": "w1"}]), stuck, stuck, stuck])

        assert isinstance(result.raised, ValueError)
        assert "not advancing" in str(result.raised)
        assert len(result.requests) == 3


def _media_window_answer(request: RecordedRequest) -> ScriptedResponse:
    if request.path == "/modern/medias":
        return _page(
            [
                {"hashed_id": "m1", "created": "2025-06-15T03:00:00Z", "cursor": "c1"},
                {"hashed_id": "gone", "created": "2026-11-01T00:00:00Z", "cursor": "c2"},
            ]
        )
    if "/gone/" in request.path:
        return ScriptedResponse(status=404, json={"error": "Media not found"})
    return _page([{"date": request.param("start_date"), "load_count": 1}])


class TestMediaDateWindows:
    @parameterized.expand(
        [
            (
                "stats_full_refresh_from_the_day_before_creation",
                "media_stats_by_date",
                "/modern/stats/medias/m1/by_date",
                None,
                [("2025-06-14", "2026-06-13"), ("2026-06-14", "2026-11-12")],
            ),
            (
                "analytics_end_date_is_exclusive",
                "media_analytics_timeseries",
                "/modern/analytics/medias/m1/timeseries",
                None,
                [("2025-06-14", "2026-06-14"), ("2026-06-14", "2026-11-13")],
            ),
            (
                "incremental_starts_at_the_watermark_day",
                "media_stats_by_date",
                "/modern/stats/medias/m1/by_date",
                date(2026, 11, 10),
                [("2026-11-10", "2026-11-12")],
            ),
            (
                "watermark_before_creation_keeps_the_creation_start",
                "media_analytics_timeseries",
                "/modern/analytics/medias/m1/timeseries",
                datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
                [("2025-06-14", "2026-06-14"), ("2026-06-14", "2026-11-13")],
            ),
        ]
    )
    def test_windows_per_media(
        self,
        _name: str,
        endpoint: str,
        media_path: str,
        last_value: Any,
        expected: list[tuple[str, str]],
    ) -> None:
        kwargs: dict[str, Any] = (
            {"should_use_incremental_field": False}
            if last_value is None
            else {
                "incremental_field": "date" if endpoint == "media_stats_by_date" else "timestamp",
                "db_incremental_field_last_value": last_value,
            }
        )
        result = _driver().run(endpoint, _media_window_answer, **kwargs)

        assert result.raised is None
        media_requests = [request for request in result.requests if request.path == media_path]
        assert [(r.param("start_date"), r.param("end_date")) for r in media_requests] == expected
        # The deleted media returns 404 once and is skipped.
        assert [request.path for request in result.requests if "/gone/" in request.path] == [
            media_path.replace("m1", "gone")
        ]
        assert result.rows == [{"date": start, "load_count": 1, "media_hashed_id": "m1"} for start, _ in expected]

    @staticmethod
    def _cursor_paged_medias(deleted: frozenset[str] = frozenset()):
        medias = [
            {"hashed_id": f"m{i}", "created": "2025-06-15T00:00:00Z", "cursor": f"c{i}"}
            for i in range(101)
            if f"m{i}" not in deleted
        ]

        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/modern/medias":
                after = request.param("cursor[after]")
                # A cursor stays valid after its media is deleted, so list by position in the full order.
                start = 0 if after is None else int(after[1:]) + 1
                listed = [media for media in medias if int(media["hashed_id"][1:]) >= start]
                return _page(listed[:100])
            return _page([{"date": request.param("start_date"), "load_count": 1}])

        return answer

    def test_walks_the_media_list_by_cursor_and_checkpoints_each_window(self) -> None:
        result = _driver().run("media_stats_by_date", self._cursor_paged_medias(), should_use_incremental_field=False)

        assert result.raised is None
        media_requests = [request for request in result.requests if request.path == "/modern/medias"]
        assert [(r.param("cursor[enabled]"), r.param("cursor[after]")) for r in media_requests] == [
            ("1", None),
            (None, "c99"),
        ]
        assert len(result.rows) == 101 * 2
        assert result.committed_states[:3] == [
            WistiaResumeConfig(media_cursor=None, media_id="m0", window_start="2026-06-14"),
            WistiaResumeConfig(media_cursor=None, media_id="m0", window_start="2026-11-13"),
            WistiaResumeConfig(media_cursor="c0", media_id="m1", window_start="2026-06-14"),
        ]

    @parameterized.expand(
        [
            ("saved_media_continues_at_its_window", frozenset(), 1 + 99 * 2),
            ("deleted_saved_media_is_skipped", frozenset({"m1"}), 99 * 2),
        ]
    )
    def test_resume_never_reads_finished_media_again(
        self, _name: str, deleted: frozenset[str], expected_rows: int
    ) -> None:
        # A full refresh appends on resume, so rows written before the interruption must not be read again.
        result = _driver().run(
            "media_stats_by_date",
            self._cursor_paged_medias(deleted),
            should_use_incremental_field=False,
            resume_state=WistiaResumeConfig(media_cursor="c0", media_id="m1", window_start="2026-06-14"),
        )

        assert result.raised is None
        assert result.requests[0].param("cursor[after]") == "c0"
        keys = [(row["media_hashed_id"], row["date"]) for row in result.rows]
        assert all(media_id != "m0" for media_id, _ in keys)
        assert len(keys) == len(set(keys)) == expected_rows
        assert ("m1", "2025-06-14") not in keys
