from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, route
from products.warehouse_sources.sources.smartrecruiters._config import SmartrecruitersSourceConfig
from products.warehouse_sources.sources.smartrecruiters.smartrecruiters import SmartRecruitersResumeConfig
from products.warehouse_sources.sources.smartrecruiters.source import SmartrecruitersSource


def _driver() -> SourceDriver:
    return SourceDriver(SmartrecruitersSource(), SmartrecruitersSourceConfig(api_key="sr-key"))


def _page(rows: list[dict[str, Any]], **extra: Any) -> ScriptedResponse:
    return ScriptedResponse(json={"content": rows, **extra})


class TestCursorPagination:
    @parameterized.expand(
        [
            ("jobs", "/jobs", "nextPageId", "pageId", {"limit": "100", "sort": "job_id"}),
            ("users", "/user-api/v201804/users", "nextPageId", "pageId", {"limit": "100"}),
            ("reports", "/reporting-api/v201804/reports", "nextPage", "page", {"limit": "100"}),
            (
                "predefined_locations",
                "/configuration/predefined-locations",
                "nextPageId",
                "pageId",
                {"pageSize": "100"},
            ),
        ]
    )
    def test_walks_pages_until_the_cursor_is_absent(
        self, endpoint: str, path: str, cursor_key: str, cursor_param: str, fixed_params: dict[str, str]
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _page([{"id": "1", "reportId": "1"}], **{cursor_key: "c2"}),
                _page([{"id": "2", "reportId": "2"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert result.paths == [path, path]
        assert result.params(cursor_param) == [None, "c2"]
        for name, value in fixed_params.items():
            assert result.params(name) == [value, value]
        assert result.saved_states == [SmartRecruitersResumeConfig(page_id="c2")]
        assert SmartRecruitersResumeConfig(page_id="c2") in result.committed_states
        assert result.requests[0].headers["x-smarttoken"] == "sr-key"

    def test_resumes_from_saved_page_id(self) -> None:
        result = _driver().run(
            "candidates",
            [_page([{"id": "9"}])],
            resume_state=SmartRecruitersResumeConfig(page_id="saved"),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["9"]
        assert result.params("pageId") == ["saved"]


class TestIncrementalRequests:
    @parameterized.expand(
        [
            ("full_refresh", False, None, None),
            ("first_incremental_sync", True, None, None),
            ("aware_utc", True, datetime(2026, 3, 4, 2, 58, 14, 123456, tzinfo=UTC), "2026-03-04T02:58:14.123Z"),
            (
                "aware_other_zone",
                True,
                datetime(2026, 3, 4, 4, 58, 14, tzinfo=ZoneInfo("Europe/Berlin")),
                "2026-03-04T03:58:14.000Z",
            ),
            ("naive", True, datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date", True, date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string", True, "2026-03-04T02:58:14.000Z", "2026-03-04T02:58:14.000Z"),
        ]
    )
    def test_updated_after_is_sent_on_every_page(
        self, _name: str, incremental: bool, last_value: Any, expected: str | None
    ) -> None:
        result = _driver().run(
            "jobs",
            [_page([{"id": "1"}], nextPageId="c2"), _page([{"id": "2"}])],
            incremental_field="updatedOn" if incremental else None,
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.params("updatedAfter") == [expected, expected]


class TestOffsetPagination:
    def test_walks_offsets_until_total_found(self) -> None:
        first = [{"id": f"o{i}"} for i in range(100)]
        result = _driver().run("offers", [_page(first, totalFound=101), _page([{"id": "o100"}], totalFound=101)])

        assert result.raised is None
        assert len(result.rows) == 101
        assert result.paths == ["/offers", "/offers"]
        assert result.params("offset") == ["0", "100"]
        assert result.params("limit") == ["100", "100"]
        assert result.saved_states == [SmartRecruitersResumeConfig(offset=100)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "offers",
            [_page([{"id": "o300"}], totalFound=301)],
            resume_state=SmartRecruitersResumeConfig(offset=300),
        )

        assert result.raised is None
        assert result.params("offset") == ["300"]


class TestSinglePageEndpoints:
    def test_does_not_follow_a_stray_cursor(self) -> None:
        result = _driver().run("departments", [_page([{"id": "d1"}], totalFound=1, nextPageId="ignored")])

        assert result.raised is None
        assert result.rows == [{"id": "d1"}]
        assert result.paths == ["/configuration/departments"]
        assert result.params("limit") == [None]


class TestJobFanout:
    @parameterized.expand([("job_hiring_team", "hiring-team"), ("job_positions", "positions")])
    def test_child_rows_carry_the_job_id(self, endpoint: str, child: str) -> None:
        result = _driver().run(
            endpoint,
            route(
                {
                    "/jobs": [_page([{"id": "J1"}], nextPageId="c2"), _page([{"id": "J2"}])],
                    f"/jobs/J1/{child}": [_page([{"id": "u1", "role": "RECRUITER"}], totalFound=1)],
                    # A job deleted between the listing and the child request.
                    f"/jobs/J2/{child}": [ScriptedResponse(status=404, json={"message": "Job not found"})],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": "u1", "role": "RECRUITER", "job_id": "J1"}]
        jobs_requests = [request for request in result.requests if request.path == "/jobs"]
        assert [request.param("sort") for request in jobs_requests] == ["job_id", "job_id"]
        assert [request.param("pageId") for request in jobs_requests] == [None, "c2"]
        child_requests = [request for request in result.requests if request.path != "/jobs"]
        assert all("limit" not in request.query for request in child_requests)
