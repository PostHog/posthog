from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, route
from products.warehouse_sources.sources.svix._config import SvixSourceConfig
from products.warehouse_sources.sources.svix.source import SvixSource
from products.warehouse_sources.sources.svix.svix import SvixResumeConfig


def _response(items: list[dict[str, Any]], iterator: str | None, done: bool) -> ScriptedResponse:
    return ScriptedResponse(json={"iterator": iterator, "done": done, "data": items})


def _driver() -> SourceDriver:
    return SourceDriver(SvixSource(), SvixSourceConfig(api_key="sk-key"))


class TestPagination:
    def test_follows_cursor_until_done(self) -> None:
        result = _driver().run(
            "applications",
            [
                _response([{"id": "app_1"}], iterator="c1", done=False),
                _response([{"id": "app_2"}], iterator="c2", done=True),
            ],
        )

        assert result.rows == [{"id": "app_1"}, {"id": "app_2"}]
        # First request carries no cursor; the second carries the cursor from page one.
        assert result.params("iterator") == [None, "c1"]
        # State saved once, carrying the cursor that fetches the second page (not the terminal one).
        assert result.saved_states == [SvixResumeConfig(iterator="c1")]

    def test_stops_when_iterator_missing(self) -> None:
        # A page that isn't `done` but returns no next cursor must still terminate.
        result = _driver().run("applications", [_response([{"id": "app_1"}], iterator=None, done=False)])

        assert result.rows == [{"id": "app_1"}]
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "applications",
            [_response([{"id": "app_2"}], iterator="c2", done=True)],
            resume_state=SvixResumeConfig(iterator="c1"),
        )

        # The first (cursorless) page must never be fetched on resume — one request, seeded with c1.
        assert result.rows == [{"id": "app_2"}]
        assert len(result.requests) == 1
        assert result.params("iterator") == ["c1"]


def _app_routes(**paths: list[ScriptedResponse]) -> Any:
    return route({"/api/v1/app": [_response([{"id": "app_1"}, {"id": "app_2"}], iterator="app_2", done=True)], **paths})


class TestFanout:
    def test_messages_walk_every_application_and_carry_the_app_id(self) -> None:
        result = _driver().run(
            "messages",
            _app_routes(
                **{
                    "/app/app_1/msg": [
                        _response([{"id": "msg_2", "timestamp": "2026-11-02T00:00:00Z"}], iterator="msg_2", done=False),
                        _response([{"id": "msg_1", "timestamp": "2026-11-01T00:00:00Z"}], iterator="msg_1", done=True),
                    ],
                    "/app/app_2/msg": [_response([], iterator=None, done=True)],
                }
            ),
        )

        assert [(row["app_id"], row["id"]) for row in result.rows] == [("app_1", "msg_2"), ("app_1", "msg_1")]
        assert result.paths == [
            "/api/v1/app",
            "/api/v1/app/app_1/msg",
            "/api/v1/app/app_1/msg",
            "/api/v1/app/app_2/msg",
        ]
        assert result.params("iterator") == [None, None, "msg_2", None]

    def test_messages_resume_skips_completed_applications(self) -> None:
        result = _driver().run(
            "messages",
            _app_routes(**{"/app/app_2/msg": [_response([{"id": "msg_9"}], iterator="msg_9", done=True)]}),
            resume_state=SvixResumeConfig(
                fanout_state={"completed": ["/app/app_1/msg"], "current": None, "child_state": None}
            ),
        )

        assert [(row["app_id"], row["id"]) for row in result.rows] == [("app_2", "msg_9")]
        assert "/api/v1/app/app_1/msg" not in result.paths

    def test_message_attempts_fan_out_over_applications_and_endpoints(self) -> None:
        result = _driver().run(
            "message_attempts",
            route(
                {
                    "/api/v1/app": [_response([{"id": "app_1"}], iterator="app_1", done=True)],
                    "/app/app_1/endpoint": [_response([{"id": "ep_1"}, {"id": "ep_2"}], iterator="ep_2", done=True)],
                    "/app/app_1/attempt/endpoint/ep_1": [
                        _response([{"id": "atmpt_2", "endpointId": "ep_1"}], iterator="atmpt_2", done=False),
                        _response([{"id": "atmpt_1", "endpointId": "ep_1"}], iterator="atmpt_1", done=True),
                    ],
                    "/app/app_1/attempt/endpoint/ep_2": [
                        _response([{"id": "atmpt_3", "endpointId": "ep_2"}], iterator="atmpt_3", done=True)
                    ],
                }
            ),
        )

        assert [(row["app_id"], row["endpointId"], row["id"]) for row in result.rows] == [
            ("app_1", "ep_1", "atmpt_2"),
            ("app_1", "ep_1", "atmpt_1"),
            ("app_1", "ep_2", "atmpt_3"),
        ]
        # The path ends in a placeholder, so this fails if the child falls back to a single page.
        assert result.params("iterator")[2:4] == [None, "atmpt_2"]
        assert set(result.params("expanded_statuses")[2:]) == {"true"}
        assert result.saved_states == []

    def test_endpoint_stats_is_one_row_per_endpoint(self) -> None:
        stats = {"success": 5, "pending": 0, "sending": 1, "fail": 2, "canceled": 0}
        result = _driver().run(
            "endpoint_stats",
            route(
                {
                    "/api/v1/app": [_response([{"id": "app_1"}], iterator="app_1", done=True)],
                    "/app/app_1/endpoint": [_response([{"id": "ep_1"}], iterator="ep_1", done=True)],
                    "/app/app_1/endpoint/ep_1/stats": [ScriptedResponse(json=stats)],
                }
            ),
        )

        assert result.rows == [{**stats, "app_id": "app_1", "endpoint_id": "ep_1"}]


class TestIncremental:
    @parameterized.expand(
        [
            # The second page reaches back past the watermark, so the walk ends there.
            ("incremental", datetime(2026, 11, 2, tzinfo=UTC), ["msg_3", "msg_2"]),
            ("incremental_iso_watermark", "2026-11-02T00:00:00+00:00", ["msg_3", "msg_2"]),
            ("full_refresh", None, ["msg_3", "msg_2", "msg_1"]),
        ]
    )
    def test_newest_first_walk_stops_at_the_watermark(
        self, _name: str, last_value: datetime | str | None, expected_ids: list[str]
    ) -> None:
        result = _driver().run(
            "messages",
            route(
                {
                    "/api/v1/app": [_response([{"id": "app_1"}], iterator="app_1", done=True)],
                    "/app/app_1/msg": [
                        _response([{"id": "msg_3", "timestamp": "2026-11-03T10:00:00Z"}], iterator="msg_3", done=False),
                        _response([{"id": "msg_2", "timestamp": "2026-11-01T23:00:00Z"}], iterator="msg_2", done=False),
                        _response([{"id": "msg_1", "timestamp": "2026-10-01T00:00:00Z"}], iterator="msg_1", done=True),
                    ],
                }
            ),
            incremental_field="timestamp" if last_value is not None else None,
            db_incremental_field_last_value=last_value,
        )

        assert [row["id"] for row in result.rows] == expected_ids
        assert result.raised is None
