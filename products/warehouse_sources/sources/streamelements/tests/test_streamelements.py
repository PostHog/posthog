from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
)
from products.warehouse_sources.sources.streamelements._config import StreamElementsSourceConfig
from products.warehouse_sources.sources.streamelements.source import StreamElementsSource
from products.warehouse_sources.sources.streamelements.streamelements import StreamElementsResumeConfig, _to_epoch_ms

CHANNEL_ID = "5b2e2007760aeb7729487dab"


def _response(payload: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=payload)


def _script(*answers: ScriptedResponse) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer the channel lookup every run starts with, and give the pipeline's requests in order."""
    queue = list(answers)

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("/channels/me"):
            return _response({"_id": CHANNEL_ID})
        if not queue:
            raise UnexpectedRequest(f"the script has no answer left for {request.method} {request.url}")
        return queue.pop(0)

    return respond


def _driver() -> SourceDriver:
    return SourceDriver(StreamElementsSource(), StreamElementsSourceConfig(api_token="jwt"))


def _tip(i: int, created_at: str = "2024-01-01T00:00:00.000Z") -> dict[str, Any]:
    return {"_id": f"tip{i}", "createdAt": created_at, "donation": {"amount": i}}


def _song(i: int) -> dict[str, Any]:
    return {"_id": f"song{i}", "song": {"videoId": f"v{i}"}, "createdAt": "2024-01-01T00:00:00.000Z"}


def _activity(i: int, created_at: str) -> dict[str, Any]:
    return {"_id": f"act{i}", "type": "follow", "createdAt": created_at}


class TestToEpochMs:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2019, 9, 6, 15, 54, 10, 202000, tzinfo=UTC), 1567785250202),
            (datetime(2019, 9, 6, 15, 54, 10, 202000), 1567785250202),
            (date(2019, 9, 6), 1567728000000),
            (1567785250202, 1567785250202),
            ("1567785250202", 1567785250202),
            ("2019-09-06T15:54:10.202Z", 1567785250202),
            ("nope", None),
        ],
    )
    def test_to_epoch_ms(self, value: Any, expected: Any) -> None:
        assert _to_epoch_ms(value) == expected


class TestTips:
    def test_incremental_adds_after_filter(self) -> None:
        result = _driver().run(
            "tips",
            _script(_response({"docs": [_tip(1)], "total": 1})),
            api_version="v2",
            incremental_field="createdAt",
            db_incremental_field_last_value=datetime(2019, 9, 6, 15, 54, 10, 202000, tzinfo=UTC),
        )

        assert result.requests[-1].param("after") == "1567785250202"

    def test_unexpected_body_shape_fails_loud(self) -> None:
        # A bare array where {"docs": [...]} is expected must raise, not silently sync 0 rows.
        result = _driver().run("tips", _script(_response([_tip(1)])), api_version="v2")

        assert isinstance(result.raised, ValueError)
        assert "data_selector" in str(result.raised)


class TestActivities:
    def test_full_page_of_identical_timestamps_still_progresses(self) -> None:
        same_ms = "2024-01-02T00:00:00.000Z"
        result = _driver().run(
            "activities",
            _script(
                _response([_activity(i, same_ms) for i in range(100)]),
                _response([_activity(200, same_ms)]),
            ),
            api_version="v2",
            resume_state=StreamElementsResumeConfig(paginator_state={"before": 1704153600001}),
        )

        activity_requests = [request for request in result.requests if "/activities/" in request.path]
        before = [int(request.param("before") or 0) for request in activity_requests]
        # before must strictly decrease even when a whole page shares the bound's millisecond,
        # otherwise pagination loops on the same window forever.
        assert len(before) == 2
        assert before[1] < before[0]


class TestOffsetEndpoints:
    def test_song_request_history_walks_pages_to_total(self) -> None:
        result = _driver().run(
            "song_request_history",
            _script(
                _response({"limit": 100, "offset": 0, "total": 101, "history": [_song(i) for i in range(100)]}),
                _response({"limit": 100, "offset": 100, "total": 101, "history": [_song(100)]}),
            ),
            api_version="v2",
        )

        history_requests = [request for request in result.requests if "/history" in request.path]
        assert {request.path for request in history_requests} == {f"/kappa/v2/songrequest/{CHANNEL_ID}/history"}
        assert [(request.param("limit"), request.param("offset")) for request in history_requests] == [
            ("100", "0"),
            ("100", "100"),
        ]
        assert len(result.rows) == 101

    @parameterized.expand(
        [
            ("null_users", {"_total": 0, "users": None}, []),
            ("rows", {"_total": 1, "users": [{"username": "viewer", "minutes": 42}]}, ["viewer"]),
        ]
    )
    def test_watchtime_leaderboard_rows(self, _name: str, body: dict[str, Any], expected: list[str]) -> None:
        result = _driver().run("watchtime_leaderboard", _script(_response(body)), api_version="v2")

        assert result.raised is None
        assert result.paths[-1] == f"/kappa/v2/points/{CHANNEL_ID}/watchtime"
        assert [row["username"] for row in result.rows] == expected


class TestSinglePageEndpoints:
    @parameterized.expand(
        [
            ("bot_commands_bare_array", "bot_commands", f"/bot/commands/{CHANNEL_ID}", [{"_id": "c1"}]),
            ("session_single_object", "session", f"/sessions/{CHANNEL_ID}", {"_id": "c1", "data": {}}),
        ]
    )
    def test_single_response_becomes_rows(self, _name: str, endpoint: str, path: str, body: Any) -> None:
        result = _driver().run(endpoint, _script(_response(body)), api_version="v2")

        assert result.paths == ["/kappa/v2/channels/me", f"/kappa/v2{path}"]
        assert [row["_id"] for row in result.rows] == ["c1"]
