import datetime as dt
from typing import Any

import pytest
import time_machine
from unittest.mock import patch

from products.warehouse_sources.sources.sdk import RESTClientRetryableError
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    error_message_matches,
    route,
    scripted_network,
)
from products.warehouse_sources.sources.zoom._config import ZoomSourceConfig
from products.warehouse_sources.sources.zoom.source import ZoomSource
from products.warehouse_sources.sources.zoom.zoom import ZoomResumeConfig, month_windows, validate_credentials

_TOKEN = ScriptedResponse(json={"access_token": "tok", "expires_in": 3599})


def _driver() -> SourceDriver:
    return SourceDriver(ZoomSource(), ZoomSourceConfig(account_id="acc", client_id="cid", client_secret="secret"))


def _probe_script(token: ScriptedResponse, probe_status: int | None = None) -> Any:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/oauth/token":
            return token
        assert probe_status is not None, f"unexpected request {request.url}"
        return ScriptedResponse(status=probe_status, json={})

    return respond


class TestZoomResumeConfig:
    def test_defaults(self) -> None:
        assert ZoomResumeConfig() == ZoomResumeConfig(next_page_token="", user_index=0, fanout_state=None)

    def test_legacy_state_still_deserializes(self) -> None:
        # State saved by the previous implementation carried only next_page_token / user_index; the
        # added fanout_state field must default so ResumableSourceManager can still rebuild it.
        assert ZoomResumeConfig(next_page_token="tok", user_index=3) == ZoomResumeConfig(
            next_page_token="tok", user_index=3, fanout_state=None
        )


class TestTopLevelRows:
    def test_first_request_omits_token_then_carries_cursor(self) -> None:
        result = _driver().run(
            "users",
            route(
                {
                    "/oauth/token": [_TOKEN],
                    "/users": [
                        ScriptedResponse(json={"users": [{"id": "u1"}], "next_page_token": "t1"}),
                        ScriptedResponse(json={"users": [{"id": "u2"}], "next_page_token": ""}),
                    ],
                }
            ),
        )

        user_requests = [request for request in result.requests if request.path == "/v2/users"]
        assert user_requests[0].param("next_page_token") is None
        assert user_requests[0].param("page_size") == "300"
        assert user_requests[1].param("next_page_token") == "t1"

    def test_resume_seeds_first_request_with_saved_token(self) -> None:
        result = _driver().run(
            "users",
            route(
                {
                    "/oauth/token": [_TOKEN],
                    "/users": [ScriptedResponse(json={"users": [{"id": "u9"}], "next_page_token": ""})],
                }
            ),
            resume_state=ZoomResumeConfig(next_page_token="resumed"),
        )

        user_requests = [request for request in result.requests if request.path == "/v2/users"]
        assert user_requests[0].param("next_page_token") == "resumed"


class TestFanOutRows:
    def test_resume_skips_already_completed_user(self) -> None:
        result = _driver().run(
            "meetings",
            route(
                {
                    "/oauth/token": [_TOKEN],
                    "/users": [ScriptedResponse(json={"users": [{"id": "u1"}, {"id": "u2"}], "next_page_token": ""})],
                    "/users/u2/meetings": [ScriptedResponse(json={"meetings": [{"id": 2}], "next_page_token": ""})],
                }
            ),
            resume_state=ZoomResumeConfig(
                fanout_state={"completed": ["/users/u1/meetings"], "current": None, "child_state": None}
            ),
        )

        # u1 was already completed, so its meetings endpoint is never requested again.
        assert result.rows == [{"id": 2}]
        assert "/v2/users/u1/meetings" not in result.paths
        assert "/v2/users/u2/meetings" in result.paths

    @pytest.mark.parametrize(
        "endpoint,parent_key,parent_path,instances_path,participants_root,parent_column",
        [
            (
                "meeting_participants",
                "meetings",
                "/users/u1/meetings",
                "/past_meetings/{id}/instances",
                "/past_meetings",
                "meeting",
            ),
            (
                "webinar_participants",
                "webinars",
                "/users/u1/webinars",
                "/past_webinars/{id}/instances",
                "/past_webinars",
                "webinar",
            ),
        ],
    )
    @pytest.mark.parametrize(
        "uuid,encoded",
        [
            ("abcDEF12==", "abcDEF12%3D%3D"),
            ("ab/c+d==", "ab%2Fc%2Bd%3D%3D"),
            ("/abcd==", "%252Fabcd%253D%253D"),
            ("ab//cd==", "ab%252F%252Fcd%253D%253D"),
        ],
    )
    def test_participants_read_each_ended_instance_by_encoded_uuid(
        self,
        endpoint: str,
        parent_key: str,
        parent_path: str,
        instances_path: str,
        participants_root: str,
        parent_column: str,
        uuid: str,
        encoded: str,
    ) -> None:
        participant = {"id": "p1", "user_id": "16778240", "join_time": "2026-01-05T10:00:00Z"}
        responses = {
            "/oauth/token": _TOKEN,
            "/v2/users": ScriptedResponse(json={"users": [{"id": "u1"}], "next_page_token": ""}),
            f"/v2{parent_path}": ScriptedResponse(json={parent_key: [{"id": 111}, {"id": 222}], "next_page_token": ""}),
            # 222 never took place: Zoom answers 404 and that parent is skipped.
            "/v2" + instances_path.format(id=111): ScriptedResponse(
                json={parent_key: [{"uuid": uuid, "start_time": "2026-01-05T10:00:00Z"}]}
            ),
            "/v2" + instances_path.format(id=222): ScriptedResponse(status=404, json={"code": 3001}),
            f"/v2{participants_root}/{encoded}/participants": ScriptedResponse(
                json={"participants": [participant], "next_page_token": ""}
            ),
        }

        def respond(request: RecordedRequest) -> ScriptedResponse:
            assert request.path in responses, f"unexpected request {request.path}"
            return responses[request.path]

        result = _driver().run(endpoint, respond)

        assert result.rows == [{**participant, f"{parent_column}_id": 111, f"{parent_column}_uuid": uuid}]

    @pytest.mark.parametrize(
        "endpoint,parent_key,parent_path,registrants_root,parent_column",
        [
            ("meeting_registrants", "meetings", "/users/u1/meetings", "/meetings", "meeting_id"),
            ("webinar_registrants", "webinars", "/users/u1/webinars", "/webinars", "webinar_id"),
        ],
    )
    def test_registrants_carry_parent_id_and_skip_unreadable_parent(
        self, endpoint: str, parent_key: str, parent_path: str, registrants_root: str, parent_column: str
    ) -> None:
        result = _driver().run(
            endpoint,
            route(
                {
                    "/oauth/token": [_TOKEN],
                    "/v2/users": [ScriptedResponse(json={"users": [{"id": "u1"}], "next_page_token": ""})],
                    parent_path: [
                        ScriptedResponse(json={parent_key: [{"id": 111}, {"id": 222}], "next_page_token": ""})
                    ],
                    f"{registrants_root}/111/registrants": [
                        ScriptedResponse(status=400, json={"code": 200, "message": "No permission."})
                    ],
                    f"{registrants_root}/222/registrants": [
                        ScriptedResponse(json={"registrants": [{"id": "r1"}], "next_page_token": "t1"}),
                        ScriptedResponse(json={"registrants": [{"id": "r2"}], "next_page_token": ""}),
                    ],
                }
            ),
        )

        assert result.rows == [{"id": "r1", parent_column: 222}, {"id": "r2", parent_column: 222}]
        registrant_requests = [r for r in result.requests if r.path == f"/v2{registrants_root}/222/registrants"]
        assert [r.param("next_page_token") for r in registrant_requests] == [None, "t1"]

    def test_expired_page_token_fails_instead_of_truncating(self) -> None:
        responses = {
            "/oauth/token": _TOKEN,
            "/v2/users": ScriptedResponse(json={"users": [{"id": "u1"}], "next_page_token": ""}),
            "/v2/users/u1/meetings": ScriptedResponse(json={"meetings": [{"id": 111}], "next_page_token": ""}),
        }

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v2/meetings/111/registrants":
                if request.param("next_page_token") is None:
                    return ScriptedResponse(json={"registrants": [{"id": "r1"}], "next_page_token": "t1"})
                return ScriptedResponse(status=400, json={"code": 300, "message": "next_page_token expired"})
            return responses[request.path]

        with patch("time.sleep"):
            result = _driver().run("meeting_registrants", respond)

        assert isinstance(result.raised, RESTClientRetryableError)

    @pytest.mark.parametrize(
        "endpoint,parent_key,parent_path,instances_root,results_suffix,parent_column",
        [
            ("meeting_polls", "meetings", "/users/u1/meetings", "/past_meetings", "polls", "meeting"),
            ("webinar_polls", "webinars", "/users/u1/webinars", "/past_webinars", "polls", "webinar"),
            ("webinar_qa", "webinars", "/users/u1/webinars", "/past_webinars", "qa", "webinar"),
        ],
    )
    def test_poll_and_qa_entries_are_numbered_per_instance(
        self,
        endpoint: str,
        parent_key: str,
        parent_path: str,
        instances_root: str,
        results_suffix: str,
        parent_column: str,
    ) -> None:
        anonymous = {"name": "Anonymous Attendee", "email": "", "question_details": [{"answer": "Yes"}]}
        named = {"name": "Ada", "email": "ada@example.com", "question_details": [{"answer": "No"}]}
        responses = {
            "/oauth/token": _TOKEN,
            "/v2/users": ScriptedResponse(json={"users": [{"id": "u1"}], "next_page_token": ""}),
            f"/v2{parent_path}": ScriptedResponse(json={parent_key: [{"id": 111}], "next_page_token": ""}),
            f"/v2{instances_root}/111/instances": ScriptedResponse(
                json={parent_key: [{"uuid": "inst1=="}, {"uuid": "inst2=="}, {"uuid": "inst3=="}]}
            ),
            # Two anonymous respondents share every field, so only their position tells them apart.
            f"/v2{instances_root}/inst1%3D%3D/{results_suffix}": ScriptedResponse(
                json={"id": 111, "questions": [anonymous, anonymous, named]}
            ),
            f"/v2{instances_root}/inst2%3D%3D/{results_suffix}": ScriptedResponse(
                json={"id": 111, "questions": [named]}
            ),
            # An instance older than a year, or one that had no poll, is skipped.
            f"/v2{instances_root}/inst3%3D%3D/{results_suffix}": ScriptedResponse(
                status=400, json={"code": 12702, "message": "Can not access a meeting a year ago."}
            ),
        }

        def respond(request: RecordedRequest) -> ScriptedResponse:
            assert request.path in responses, f"unexpected request {request.path}"
            return responses[request.path]

        result = _driver().run(endpoint, respond)

        assert result.raised is None
        assert [
            (row[f"{parent_column}_id"], row[f"{parent_column}_uuid"], row["entry_index"], row["name"])
            for row in result.rows
        ] == [
            (111, "inst1==", 0, "Anonymous Attendee"),
            (111, "inst1==", 1, "Anonymous Attendee"),
            (111, "inst1==", 2, "Ada"),
            (111, "inst2==", 0, "Ada"),
        ]
        assert all("_uuid_path" not in row for row in result.rows)

    @pytest.mark.parametrize(
        "endpoint,child_path,data_key,child_row,parent_column",
        [
            ("webinar_panelists", "/webinars/{id}/panelists", "panelists", {"id": "pan1", "name": "Ada"}, "webinar_id"),
            ("webinar_instances", "/past_webinars/{id}/instances", "webinars", {"uuid": "inst=="}, "webinar_id"),
        ],
    )
    def test_single_page_child_skips_invalid_parent_instead_of_retrying(
        self, endpoint: str, child_path: str, data_key: str, child_row: dict[str, Any], parent_column: str
    ) -> None:
        responses = {
            "/oauth/token": _TOKEN,
            "/v2/users": ScriptedResponse(json={"users": [{"id": "u1"}], "next_page_token": ""}),
            "/v2/users/u1/webinars": ScriptedResponse(
                json={"webinars": [{"id": 111}, {"id": 222}], "next_page_token": ""}
            ),
            # Without a page token, code 300 means the webinar ID is invalid, which a retry cannot fix.
            "/v2" + child_path.format(id=111): ScriptedResponse(
                status=400, json={"code": 300, "message": "Invalid webinar ID."}
            ),
            "/v2" + child_path.format(id=222): ScriptedResponse(json={data_key: [child_row]}),
        }

        def respond(request: RecordedRequest) -> ScriptedResponse:
            assert request.path in responses, f"unexpected request {request.path}"
            return responses[request.path]

        with patch("time.sleep"):
            result = _driver().run(endpoint, respond)

        assert result.raised is None
        assert result.rows == [{**child_row, parent_column: 222}]
        assert result.paths.count("/v2" + child_path.format(id=111)) == 1


class TestInstanceRows:
    @pytest.mark.parametrize(
        "endpoint,parent_key,parent_path,instances_root,parent_column",
        [
            ("meeting_instances", "meetings", "/users/u1/meetings", "/past_meetings", "meeting_id"),
            ("webinar_instances", "webinars", "/users/u1/webinars", "/past_webinars", "webinar_id"),
        ],
    )
    def test_instances_carry_parent_id_without_the_path_helper(
        self, endpoint: str, parent_key: str, parent_path: str, instances_root: str, parent_column: str
    ) -> None:
        instance = {"uuid": "ab/c+d==", "start_time": "2026-01-05T10:00:00Z"}
        result = _driver().run(
            endpoint,
            route(
                {
                    "/oauth/token": [_TOKEN],
                    "/v2/users": [ScriptedResponse(json={"users": [{"id": "u1"}], "next_page_token": ""})],
                    parent_path: [ScriptedResponse(json={parent_key: [{"id": 111}], "next_page_token": ""})],
                    f"{instances_root}/111/instances": [ScriptedResponse(json={parent_key: [instance]})],
                }
            ),
        )

        assert result.rows == [{**instance, parent_column: 111}]


class TestMonthlyWindowRows:
    @pytest.fixture(autouse=True)
    def _pin_clock(self) -> Any:
        with time_machine.travel(dt.datetime(2026, 11, 17, 12, tzinfo=dt.UTC), tick=False):
            yield

    @pytest.mark.parametrize(
        "start,end,expected",
        [
            (dt.date(2026, 11, 1), dt.date(2026, 11, 17), [("2026-11-01", "2026-11-17")]),
            (
                dt.date(2026, 1, 20),
                dt.date(2026, 3, 2),
                [("2026-01-20", "2026-01-31"), ("2026-02-01", "2026-02-28"), ("2026-03-01", "2026-03-02")],
            ),
            (dt.date(2025, 12, 31), dt.date(2026, 1, 1), [("2025-12-31", "2025-12-31"), ("2026-01-01", "2026-01-01")]),
            (dt.date(2026, 11, 18), dt.date(2026, 11, 17), []),
        ],
    )
    def test_month_windows(self, start: dt.date, end: dt.date, expected: list[tuple[str, str]]) -> None:
        assert [(w.start.isoformat(), w.end.isoformat()) for w in month_windows(start, end)] == expected

    @pytest.mark.parametrize(
        "inputs,expected_starts",
        [
            # Zoom serves only the last six months: the current month and the five before it.
            ({}, ["2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01", "2026-10-01", "2026-11-01"]),
            (
                {"incremental_field": "period_start", "db_incremental_field_last_value": dt.date(2026, 10, 1)},
                ["2026-10-01", "2026-11-01"],
            ),
            (
                {"incremental_field": "period_start", "db_incremental_field_last_value": "2026-11-01"},
                ["2026-11-01"],
            ),
            # A cursor older than Zoom's six months is clamped instead of sending a rejected range.
            (
                {"incremental_field": "period_start", "db_incremental_field_last_value": dt.date(2025, 1, 1)},
                ["2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01", "2026-10-01", "2026-11-01"],
            ),
        ],
    )
    def test_report_users_reads_both_reports_per_month(
        self, inputs: dict[str, Any], expected_starts: list[str]
    ) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return _TOKEN
            assert request.path == "/v2/report/users", f"unexpected request {request.url}"
            if request.param("next_page_token") is None:
                user = {"id": f"{request.param('type')}-{request.param('from')}", "meetings": 3}
                return ScriptedResponse(json={"users": [user], "next_page_token": "t1"})
            return ScriptedResponse(json={"users": [], "next_page_token": ""})

        result = _driver().run("report_users", respond, **inputs)

        first_pages = [
            r for r in result.requests if r.path == "/v2/report/users" and r.param("next_page_token") is None
        ]
        assert [(r.param("from"), r.param("type")) for r in first_pages] == [
            (start, report_type) for start in expected_starts for report_type in ("active", "inactive")
        ]
        assert first_pages[-1].param("to") == "2026-11-17"
        assert result.rows[-1] == {
            "id": "inactive-2026-11-01",
            "meetings": 3,
            "period_start": "2026-11-01",
            "period_end": "2026-11-17",
            "report_type": "inactive",
        }
        assert len(result.rows) == 2 * len(expected_starts)

    @pytest.mark.parametrize(
        "inputs,expected_months",
        [
            ({}, [(2026, 6), (2026, 7), (2026, 8), (2026, 9), (2026, 10), (2026, 11)]),
            # The cursor's month is read again, because it may have been partial.
            (
                {"incremental_field": "date", "db_incremental_field_last_value": dt.date(2026, 10, 15)},
                [(2026, 10), (2026, 11)],
            ),
            ({"incremental_field": "date", "db_incremental_field_last_value": "2026-11-30"}, [(2026, 11)]),
            (
                {"incremental_field": "date", "db_incremental_field_last_value": dt.date(2025, 1, 1)},
                [(2026, 6), (2026, 7), (2026, 8), (2026, 9), (2026, 10), (2026, 11)],
            ),
        ],
    )
    def test_report_daily_reads_one_request_per_month(
        self, inputs: dict[str, Any], expected_months: list[tuple[int, int]]
    ) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return _TOKEN
            assert request.path == "/v2/report/daily", f"unexpected request {request.url}"
            year, month = int(str(request.param("year"))), int(str(request.param("month")))
            day = {"date": f"{year}-{month:02d}-01", "meetings": 2, "meeting_minutes": 34}
            return ScriptedResponse(json={"year": year, "month": month, "dates": [day]})

        result = _driver().run("report_daily", respond, **inputs)

        requests = [r for r in result.requests if r.path == "/v2/report/daily"]
        assert [(int(str(r.param("year"))), int(str(r.param("month")))) for r in requests] == expected_months
        assert [row["date"] for row in result.rows] == [f"{y}-{m:02d}-01" for y, m in expected_months]
        assert result.raised is None

    @pytest.mark.parametrize(
        "inputs,expected_first_range,expected_window_count",
        [
            # A first sync starts before AI Companion summaries existed.
            ({}, ("2023-01-01T00:00:00Z", "2023-01-31T23:59:59Z"), 47),
            (
                {
                    "incremental_field": "summary_created_time",
                    "db_incremental_field_last_value": dt.datetime(2026, 11, 3, 23, 30, tzinfo=dt.UTC),
                },
                ("2026-11-03T00:00:00Z", "2026-11-17T23:59:59Z"),
                1,
            ),
            (
                {
                    "incremental_field": "summary_created_time",
                    "db_incremental_field_last_value": "2026-10-20T08:00:00Z",
                },
                ("2026-10-20T00:00:00Z", "2026-10-31T23:59:59Z"),
                2,
            ),
        ],
    )
    def test_meeting_summaries_walk_month_windows_by_creation_time(
        self, inputs: dict[str, Any], expected_first_range: tuple[str, str], expected_window_count: int
    ) -> None:
        summary = {"meeting_uuid": "sum==", "summary_created_time": "2026-11-05T10:00:00Z"}

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return _TOKEN
            assert request.path == "/v2/meetings/meeting_summaries", f"unexpected request {request.url}"
            if not str(request.param("from")).startswith("2026-11"):
                return ScriptedResponse(json={"summaries": [], "next_page_token": ""})
            if request.param("next_page_token") is None:
                return ScriptedResponse(json={"summaries": [summary], "next_page_token": "t1"})
            return ScriptedResponse(json={"summaries": [{**summary, "meeting_uuid": "sum2=="}], "next_page_token": ""})

        result = _driver().run("meeting_summaries", respond, **inputs)

        first_pages = [
            r
            for r in result.requests
            if r.path == "/v2/meetings/meeting_summaries" and r.param("next_page_token") is None
        ]
        assert (first_pages[0].param("from"), first_pages[0].param("to")) == expected_first_range
        assert first_pages[-1].param("to") == "2026-11-17T23:59:59Z"
        assert len(first_pages) == expected_window_count
        assert {r.param("time_filter_field") for r in first_pages} == {"summary_created_time"}
        assert result.rows == [summary, {**summary, "meeting_uuid": "sum2=="}]

    @pytest.mark.parametrize(
        "inputs,expected_u1_ranges",
        [
            # A first sync starts at the user's creation date.
            ({}, [("2026-09-20", "2026-09-30"), ("2026-10-01", "2026-10-31"), ("2026-11-01", "2026-11-17")]),
            # An incremental sync starts at the cursor's day; Zoom takes UTC dates.
            (
                {
                    "incremental_field": "start_time",
                    "db_incremental_field_last_value": dt.datetime(2026, 11, 3, 23, 30, tzinfo=dt.UTC),
                },
                [("2026-11-03", "2026-11-17")],
            ),
        ],
    )
    def test_recordings_walk_each_user_by_month(
        self, inputs: dict[str, Any], expected_u1_ranges: list[tuple[str, str]]
    ) -> None:
        recording = {"uuid": "rec==", "start_time": "2026-11-05T10:00:00Z", "total_size": 1024}
        users_by_status = {
            "active": [{"id": "u1", "created_at": "2026-09-20T08:00:00Z"}],
            # A deactivated user keeps their recordings; this one has none, which Zoom answers with a 404.
            "inactive": [{"id": "u2", "created_at": "2026-11-10T08:00:00Z"}],
        }

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return _TOKEN
            if request.path == "/v2/users":
                return ScriptedResponse(
                    json={"users": users_by_status[str(request.param("status"))], "next_page_token": ""}
                )
            if request.path == "/v2/users/u2/recordings":
                return ScriptedResponse(status=404, json={"code": 3301, "message": "There is no recording."})
            assert request.path == "/v2/users/u1/recordings", f"unexpected request {request.url}"
            if request.param("from") == "2026-11-01" or request.param("from") == "2026-11-03":
                if request.param("next_page_token") is None:
                    return ScriptedResponse(
                        json={"meetings": [{**recording, "recording_play_passcode": "pass"}], "next_page_token": "t1"}
                    )
                return ScriptedResponse(json={"meetings": [{**recording, "uuid": "rec2=="}], "next_page_token": ""})
            return ScriptedResponse(json={"meetings": [], "next_page_token": ""})

        result = _driver().run("recordings", respond, **inputs)

        u1_first_pages = [
            r for r in result.requests if r.path == "/v2/users/u1/recordings" and r.param("next_page_token") is None
        ]
        assert [(r.param("from"), r.param("to")) for r in u1_first_pages] == expected_u1_ranges
        assert result.rows == [recording, {**recording, "uuid": "rec2=="}]
        assert "/v2/users/u2/recordings" in result.paths
        # The user list is read to its end before any recording request, so its page token cannot expire.
        api_paths = [r.path for r in result.requests if r.path != "/oauth/token"]
        assert api_paths[:2] == ["/v2/users", "/v2/users"]
        assert "/v2/users" not in api_paths[2:]
        assert result.raised is None

    def test_recordings_fail_on_missing_scope_instead_of_returning_nothing(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return _TOKEN
            if request.path == "/v2/users":
                return ScriptedResponse(
                    json={"users": [{"id": "u1", "created_at": "2026-11-01T08:00:00Z"}], "next_page_token": ""}
                )
            return ScriptedResponse(
                status=400, json={"code": 4711, "message": "Invalid access token, does not contain scopes."}
            )

        result = _driver().run("recordings", respond)

        assert result.raised is not None
        assert result.rows == []
        # A missing scope never clears on retry, so the job must stop retrying instead of
        # burning its whole retry budget on the same 400.
        assert error_message_matches(str(result.raised), ZoomSource().get_non_retryable_errors())


class TestZoomSourceResponse:
    @pytest.mark.parametrize(
        "endpoint,resumable",
        [
            ("users", True),
            ("meetings", True),
            ("webinars", True),
            ("meeting_registrants", False),
            ("webinar_registrants", False),
            ("meeting_participants", False),
            ("webinar_participants", False),
            ("meeting_instances", False),
            ("webinar_instances", False),
            ("groups", True),
            ("group_members", True),
            ("report_users", False),
            ("recordings", False),
            ("report_daily", False),
            ("meeting_summaries", False),
            ("webinar_panelists", False),
            ("meeting_polls", False),
            ("webinar_polls", False),
            ("webinar_qa", False),
        ],
    )
    def test_chained_tables_are_not_resumable(self, endpoint: str, resumable: bool) -> None:
        assert ZoomSource().resume_covers_run(incremental_or_append=False, schema_name=endpoint) is resumable

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return _TOKEN
            return ScriptedResponse(json={"users": [], "next_page_token": ""})

        result = _driver().run(endpoint, respond)

        assert result.response is not None
        assert result.response.supports_resume is resumable

    @pytest.mark.parametrize("endpoint", ["users", "meetings", "webinars"])
    def test_primary_keys_per_endpoint(self, endpoint: str) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return _TOKEN
            return ScriptedResponse(json={"users": [], "meetings": [], "webinars": [], "next_page_token": ""})

        result = _driver().run(endpoint, respond)

        assert result.response is not None
        assert result.response.primary_keys == ["id"]


class TestValidateCredentials:
    def test_bad_credentials_return_false(self) -> None:
        with scripted_network(_probe_script(ScriptedResponse(status=400, json={"error": "invalid_client"}))):
            ok, error = validate_credentials("acc", "cid", "secret")
        assert ok is False
        assert error is not None

    def test_source_create_only_validates_token(self) -> None:
        with scripted_network(_probe_script(_TOKEN)) as network:
            ok, error = validate_credentials("acc", "cid", "secret", schema_name=None)
        assert ok is True
        assert error is None
        # No scoped endpoint probe at source-create.
        assert [request.path for request in network.requests_log] == ["/oauth/token"]

    def test_schema_probe_success(self) -> None:
        with scripted_network(_probe_script(_TOKEN, probe_status=200)):
            ok, error = validate_credentials("acc", "cid", "secret", schema_name="users")
        assert ok is True
        assert error is None

    def test_schema_probe_missing_scope_401(self) -> None:
        with scripted_network(_probe_script(_TOKEN, probe_status=401)):
            ok, error = validate_credentials("acc", "cid", "secret", schema_name="users")
        assert ok is False
        assert error is not None and "scope" in error

    def test_schema_probe_unexpected_status(self) -> None:
        with scripted_network(_probe_script(_TOKEN, probe_status=500)):
            ok, error = validate_credentials("acc", "cid", "secret", schema_name="users")
        assert ok is False
        assert error is not None and "500" in error
