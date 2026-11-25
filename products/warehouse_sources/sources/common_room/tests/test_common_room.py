import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
import time_machine

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.sources.common_room._config import CommonRoomSourceConfig
from products.warehouse_sources.sources.common_room.common_room import (
    INVALID_TOKEN_MESSAGE,
    RATE_LIMITED_MESSAGE,
    CommonRoomResumeConfig,
    retry_after_from_wait_ms,
    validate_credentials,
)
from products.warehouse_sources.sources.common_room.source import CommonRoomSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


def _driver() -> SourceDriver:
    return SourceDriver(CommonRoomSource(), CommonRoomSourceConfig(api_token="cr-token"))


def _page(rows: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"success": True, "data": rows, "meta": {"nextCursor": next_cursor}})


def _activity(activity_id: str, activity_time: str = "2026-03-01T10:00:00.000Z") -> dict[str, Any]:
    return {"id": activity_id, "type": "SlackPost", "activityTime": activity_time, "contactId": "c_1"}


def _rate_limited(wait_ms: Any, headers: dict[str, str] | None = None) -> Response:
    response = Response()
    response.status_code = 429
    response._content = json.dumps(
        {"reason": "Rate limited", "rateLimit": {"intervalLimit": 10, "waitMs": wait_ms}}
    ).encode()
    response.headers.update(headers or {})
    return response


class TestPagination:
    def test_follows_next_cursor_to_the_terminal_page_and_saves_the_cursor_first(self) -> None:
        result = _driver().run(
            "contacts",
            [
                _page([{"id": "c_1", "name": "Ada"}, {"id": "c_2", "name": "Grace"}], "cursor-2"),
                _page([{"id": "c_3", "name": "Linus"}], None),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["c_1", "c_2", "c_3"]
        assert result.paths == ["/api/v2/contacts", "/api/v2/contacts"]
        assert result.params("cursor") == [None, "cursor-2"]
        # Common Room returns only id and name unless `cols` asks for more, on every page.
        assert all("primaryEmail" in (cols or "") for cols in result.params("cols"))
        assert all("cf_*" in (cols or "") for cols in result.params("cols"))
        assert result.params("limit") == ["500", "500"]
        assert all(request.headers["authorization"] == "Bearer cr-token" for request in result.requests)
        assert result.committed_states == [CommonRoomResumeConfig(paginator_state={"cursor": "cursor-2"})]

    def test_resumes_from_the_saved_cursor(self) -> None:
        result = _driver().run(
            "tags",
            [_page([{"id": "l_9", "name": "Champion"}])],
            resume_state=CommonRoomResumeConfig(paginator_state={"cursor": "cursor-5"}),
        )

        assert result.raised is None
        assert result.params("cursor") == ["cursor-5"]
        assert [row["id"] for row in result.rows] == ["l_9"]

    def test_unpaginated_endpoint_sends_no_page_params_and_reads_one_page(self) -> None:
        result = _driver().run(
            "custom_fields",
            [ScriptedResponse(json={"success": True, "data": [{"id": "cf_1", "name": "Plan"}]})],
        )

        assert result.raised is None
        assert result.rows == [{"id": "cf_1", "name": "Plan"}]
        assert result.params("limit") == [None]
        assert result.params("cursor") == [None]


class TestIncrementalRequests:
    @parameterized.expand(
        [
            ("watermark_as_utc_datetime", True, datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05.000Z"),
            (
                "watermark_in_another_timezone",
                True,
                datetime(2026, 1, 2, 5, 4, 5, 250000, tzinfo=timezone(timedelta(hours=2))),
                "2026-01-02T03:04:05.250Z",
            ),
            ("first_incremental_sync_reads_everything", True, None, None),
            ("full_refresh_ignores_a_watermark", False, datetime(2026, 1, 2, tzinfo=UTC), None),
        ]
    )
    def test_start_date_filter_and_sort(
        self, _name: str, incremental: bool, watermark: Any, expected_start: str | None
    ) -> None:
        result = _driver().run(
            "activities",
            [_page([_activity("a_1")], "cursor-2"), _page([_activity("a_2", "2026-03-02T10:00:00.000Z")], None)],
            incremental_field="activityTime",
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a_1", "a_2"]
        assert result.params("startDate") == [expected_start, expected_start]
        # `sort_mode="asc"` relies on this ascending sort, on every page.
        assert result.params("sort") == ["activityTime", "activityTime"]
        assert result.params("direction") == ["asc", "asc"]
        assert result.response is not None
        assert result.response.sort_mode == ("asc" if incremental else None)


class TestFanOut:
    @parameterized.expand(
        [
            (
                "objects",
                "/api/v2/object-types",
                "/api/v2/objects",
                "objectTypeId",
                ["cot_1", "cot_2"],
                "recordKey,segments,tags,url,cf_*",
                "id",
            ),
            (
                "job_openings",
                "/api/v2/organizations",
                "/api/v2/job-openings",
                "organizationId",
                ["o_1", "o_2"],
                "jobDescription",
                "firstSeenAt",
            ),
            (
                "news_items",
                "/api/v2/organizations",
                "/api/v2/news-items",
                "organizationId",
                ["o_1", "o_2"],
                None,
                "publishedAt",
            ),
        ]
    )
    def test_lists_the_children_of_each_parent_and_keeps_the_parent_id(
        self,
        endpoint: str,
        parent_path: str,
        child_path: str,
        param: str,
        parent_ids: list[str],
        child_cols: str | None,
        child_sort: str,
    ) -> None:
        first, second = parent_ids
        result = _driver().run(
            endpoint,
            [
                _page([{"id": first, "name": "Acme"}, {"id": second, "name": "Initech"}]),
                _page([{"id": "x_1", "name": "One"}], "cursor-2"),
                _page([{"id": "x_2", "name": "Two"}], None),
                # The same child id under a second parent stays a separate row.
                _page([{"id": "x_1", "name": "One again"}], None),
            ],
        )

        assert result.raised is None
        assert result.paths == [parent_path, child_path, child_path, child_path]
        assert result.params(param) == [None, first, first, second]
        assert result.params("cursor") == [None, None, "cursor-2", None]
        # The fan-out reads only the parent id, so the parent listing asks for no extra columns.
        assert result.params("cols") == [None, child_cols, child_cols, child_cols]
        assert result.params("sort")[1:] == [child_sort] * 3
        assert [(row[param], row["id"]) for row in result.rows] == [(first, "x_1"), (first, "x_2"), (second, "x_1")]
        assert all(not key.startswith("_") for row in result.rows for key in row)
        assert (
            result.saved_states[0].paginator_state["current"] == f"{child_path.removeprefix('/api/v2')}?{param}={first}"
        )
        assert result.saved_states[0].paginator_state["child_state"] == {"cursor": "cursor-2"}

    @parameterized.expand([("job_openings", "/job-openings"), ("news_items", "/news-items")])
    def test_organization_fan_out_resumes_at_the_saved_organization_page(self, endpoint: str, path: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _page([{"id": "o_3", "name": "Globex"}, {"id": "o_4", "name": "Hooli"}], None),
                _page([{"id": "x_7", "name": "Late"}], None),
                _page([{"id": "x_9", "name": "Next"}], None),
            ],
            resume_state=CommonRoomResumeConfig(
                paginator_state={
                    "completed": [],
                    "current": f"{path}?organizationId=o_3",
                    "child_state": {"cursor": "cursor-7"},
                    "parent": {"cursor": "org-cursor-2"},
                }
            ),
        )

        assert result.raised is None
        assert result.params("cursor") == ["org-cursor-2", "cursor-7", None]
        assert result.params("organizationId") == [None, "o_3", "o_4"]
        assert [(row["organizationId"], row["id"]) for row in result.rows] == [("o_3", "x_7"), ("o_4", "x_9")]

    def test_resume_skips_finished_object_types_and_continues_the_current_one(self) -> None:
        result = _driver().run(
            "objects",
            [
                ScriptedResponse(
                    json={
                        "success": True,
                        "data": [
                            {"id": "cot_1", "name": "Accounts"},
                            {"id": "cot_2", "name": "Deals"},
                            {"id": "cot_3", "name": "Tickets"},
                        ],
                    }
                ),
                _page([{"id": "co_7", "name": "Late deal"}], None),
                _page([{"id": "co_9", "name": "Ticket"}], None),
            ],
            resume_state=CommonRoomResumeConfig(
                paginator_state={
                    "completed": ["/objects?objectTypeId=cot_1"],
                    "current": "/objects?objectTypeId=cot_2",
                    "child_state": {"cursor": "cursor-7"},
                }
            ),
        )

        assert result.raised is None
        assert result.params("objectTypeId") == [None, "cot_2", "cot_3"]
        assert result.params("cursor") == [None, "cursor-7", None]
        assert [(row["objectTypeId"], row["id"]) for row in result.rows] == [("cot_2", "co_7"), ("cot_3", "co_9")]


class TestRateLimit:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel(datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC), tick=False):
            yield

    @parameterized.expand(
        [
            ("wait_ms_in_body", _rate_limited(12_500), "13"),
            ("short_wait_ms_waits_one_second", _rate_limited(10), "1"),
            (
                "wait_ms_wins_over_the_iso_header",
                _rate_limited(2_000, {"Retry-After": "2026-03-01T12:05:00Z"}),
                "2",
            ),
            ("iso_header_without_wait_ms", _rate_limited(None, {"Retry-After": "2026-03-01T12:00:30Z"}), "30"),
            ("iso_header_in_the_past", _rate_limited(None, {"Retry-After": "2026-03-01T11:00:00Z"}), "1"),
            ("no_wait_at_all", _rate_limited(None), None),
            ("seconds_header_stays", _rate_limited("soon", {"Retry-After": "7"}), "7"),
        ]
    )
    def test_retry_after_comes_from_the_rate_limit_body(
        self, _name: str, response: Response, expected: str | None
    ) -> None:
        assert retry_after_from_wait_ms(response).headers.get("Retry-After") == expected

    def test_other_statuses_are_not_changed(self) -> None:
        response = _rate_limited(5_000)
        response.status_code = 500

        assert retry_after_from_wait_ms(response).headers.get("Retry-After") is None

    def test_sync_reads_the_wait_from_the_body(self) -> None:
        # A wait longer than the client allows fails the request with the wait in the message, which
        # shows that the client read `waitMs` and not the ISO header it cannot parse.
        result = _driver().run(
            "segments",
            always(
                ScriptedResponse(
                    status=429,
                    json={"reason": "Rate limited", "rateLimit": {"waitMs": 3_600_000}},
                    headers={"Retry-After": "2026-03-01T13:00:00Z"},
                )
            ),
        )

        assert result.raised is not None
        assert "asked for a wait of 3600 seconds" in str(result.raised)
        assert "cr-token" not in str(result.raised)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid_token", ScriptedResponse(json={"jti": "x", "communityName": "Acme"}), True, None),
            # Common Room answers a token that is not valid with a 403.
            (
                "invalid_token",
                ScriptedResponse(status=403, json={"reason": "Token not valid"}),
                False,
                INVALID_TOKEN_MESSAGE,
            ),
            (
                "rate_limited",
                ScriptedResponse(status=429, json={"reason": "Rate limited"}),
                False,
                RATE_LIMITED_MESSAGE,
            ),
        ]
    )
    def test_probes_the_token_status(
        self, _name: str, answer: ScriptedResponse, valid: bool, message: str | None
    ) -> None:
        with scripted_network(always(answer)) as network:
            result = validate_credentials("cr-token")

        assert result == (valid, message)
        assert {request.path for request in network.requests_log} == {"/api/v2/api-token-status"}
        assert all(request.headers["authorization"] == "Bearer cr-token" for request in network.requests_log)
