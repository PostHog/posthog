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
                "audit_events",
                "/audit-api/v201910/audit-events",
                "nextPageId",
                "nextPageId",
                {"limit": "100", "eventDateAfter": "2010-01-01T00:00:00.000Z"},
            ),
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

    @parameterized.expand(
        [
            ("first_incremental_sync", None, "2010-01-01T00:00:00.000Z"),
            ("watermark", datetime(2026, 3, 4, 2, 58, 14, 5000, tzinfo=UTC), "2026-03-04T02:58:14.005Z"),
        ]
    )
    def test_audit_events_send_the_watermark_as_event_date_after(
        self, _name: str, last_value: Any, expected: str
    ) -> None:
        result = _driver().run(
            "audit_events",
            [_page([{"id": "e1"}], nextPageId="c2"), _page([{"id": "e2"}])],
            incremental_field="eventDate",
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.params("eventDateAfter") == [expected, expected]
        assert result.params("updatedAfter") == [None, None]


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


def _candidate(candidate_id: str, *job_ids: str) -> dict[str, Any]:
    primary, *secondary = job_ids or (None,)
    row: dict[str, Any] = {
        "id": candidate_id,
        "secondaryAssignments": [{"job": {"id": job_id}} for job_id in secondary],
    }
    if primary is not None:
        row["primaryAssignment"] = {"job": {"id": primary}, "status": "NEW"}
    return row


_NOT_FOUND = ScriptedResponse(status=404, json={"message": "Not found"})

# Page one: C1 applied to J1 and J2 (J1 also listed again as a secondary assignment), C2 has no
# assignment. Page two: C3 applied to J3, which is deleted before its child request.
_CANDIDATE_PAGES = [
    _page([_candidate("C1", "J1", "J1", "J2"), _candidate("C2")], nextPageId="c2"),
    _page([_candidate("C3", "J3")]),
]


class TestPerApplicationEndpoints:
    @parameterized.expand(
        [
            (
                "candidate_status_history",
                {
                    "/candidates/C1/jobs/J1/status/history": [
                        _page([{"changedOn": "2026-01-02T00:00:00.000Z", "status": "IN_REVIEW"}])
                    ],
                    "/candidates/C1/jobs/J2/status/history": [_page([])],
                    "/candidates/C3/jobs/J3/status/history": [_NOT_FOUND],
                },
                [
                    {
                        "changedOn": "2026-01-02T00:00:00.000Z",
                        "status": "IN_REVIEW",
                        "candidate_id": "C1",
                        "job_id": "J1",
                    }
                ],
                [
                    ("/candidates/C1/jobs/J1/status/history", {}),
                    ("/candidates/C1/jobs/J2/status/history", {}),
                    ("/candidates/C3/jobs/J3/status/history", {}),
                ],
            ),
            (
                "reviews",
                {
                    "/reviews": [
                        ScriptedResponse(json=[{"id": "r1", "candidateId": "C1", "jobId": "J1", "overallRating": 4}]),
                        ScriptedResponse(json=[]),
                        _NOT_FOUND,
                    ],
                },
                [{"id": "r1", "candidateId": "C1", "jobId": "J1", "overallRating": 4}],
                [
                    ("/reviews-api/v201910/reviews", {"candidateId": "C1", "jobId": "J1"}),
                    ("/reviews-api/v201910/reviews", {"candidateId": "C1", "jobId": "J2"}),
                    ("/reviews-api/v201910/reviews", {"candidateId": "C3", "jobId": "J3"}),
                ],
            ),
            (
                "interviews",
                {
                    "/candidates/C1/jobs/J1": [ScriptedResponse(json={"applicationId": "A1", "status": "INTERVIEW"})],
                    "/candidates/C1/jobs/J2": [ScriptedResponse(json={"applicationId": "A2", "status": "NEW"})],
                    "/candidates/C3/jobs/J3": [_NOT_FOUND],
                    "/interviews": [_page([{"id": "i1", "jobId": "J1", "candidate": {"id": "C1"}}]), _page([])],
                },
                [{"id": "i1", "jobId": "J1", "candidate": {"id": "C1"}}],
                [
                    ("/candidates/C1/jobs/J1", {}),
                    ("/interviews-api/v201904/interviews", {"applicationId": "A1"}),
                    ("/candidates/C1/jobs/J2", {}),
                    ("/interviews-api/v201904/interviews", {"applicationId": "A2"}),
                    ("/candidates/C3/jobs/J3", {}),
                ],
            ),
        ]
    )
    def test_reads_each_job_application_of_every_candidate_page(
        self,
        endpoint: str,
        children: dict[str, list[ScriptedResponse]],
        expected_rows: list[dict[str, Any]],
        expected_child_requests: list[tuple[str, dict[str, str]]],
    ) -> None:
        result = _driver().run(endpoint, route({"/candidates": _CANDIDATE_PAGES, **children}))

        assert result.raised is None
        assert result.rows == expected_rows
        candidate_requests = [request for request in result.requests if request.path == "/candidates"]
        assert [request.param("pageId") for request in candidate_requests] == [None, "c2"]
        assert [request.param("limit") for request in candidate_requests] == ["100", "100"]
        child_requests = [
            (request.path, {name: request.param(name) or "" for name in expected})
            for request, (_, expected) in zip(
                [request for request in result.requests if request.path != "/candidates"], expected_child_requests
            )
        ]
        assert child_requests == expected_child_requests
        assert len(result.requests) == 2 + len(expected_child_requests)
        # The last pair of a page that has a next page stages that next page.
        assert result.saved_states == [
            SmartRecruitersResumeConfig(candidate_page_id=None, last_candidate_id="C1", last_job_id="J1"),
            SmartRecruitersResumeConfig(candidate_page_id="c2"),
            SmartRecruitersResumeConfig(candidate_page_id="c2", last_candidate_id="C3", last_job_id="J3"),
        ]
        assert result.requests[0].headers["x-smarttoken"] == "sr-key"

    @parameterized.expand(
        [
            ("after_the_saved_pair", [_page([_candidate("C3", "J3", "J4")])], "J3", ["J4"]),
            # The saved pair is gone from the page, so the page is read again from its start.
            ("saved_pair_is_gone", [_page([_candidate("C3", "J4", "J5")])], "J3", ["J4", "J5"]),
            (
                "saved_pair_was_the_last_on_its_page",
                [_page([_candidate("C3", "J3")], nextPageId="c3"), _page([_candidate("C4", "J4")])],
                "J3",
                ["J4"],
            ),
        ]
    )
    def test_resumes_after_the_saved_pair_of_the_saved_candidate_page(
        self, _name: str, candidate_pages: list[ScriptedResponse], last_job_id: str, expected_job_ids: list[str]
    ) -> None:
        result = _driver().run(
            "reviews",
            route(
                {
                    "/candidates": candidate_pages,
                    "/reviews": [ScriptedResponse(json=[]) for _ in expected_job_ids],
                }
            ),
            resume_state=SmartRecruitersResumeConfig(
                candidate_page_id="c2", last_candidate_id="C3", last_job_id=last_job_id
            ),
        )

        assert result.raised is None
        candidate_requests = [request for request in result.requests if request.path == "/candidates"]
        assert candidate_requests[0].param("pageId") == "c2"
        review_requests = [request for request in result.requests if request.path != "/candidates"]
        assert [request.param("jobId") for request in review_requests] == expected_job_ids

    def test_checkpoints_candidate_pages_with_no_applications(self) -> None:
        result = _driver().run(
            "reviews",
            route(
                {
                    "/candidates": [
                        _page([_candidate("C1")], nextPageId="c2"),
                        _page([_candidate("C2")], nextPageId="c3"),
                        _page([_candidate("C3", "J3")]),
                    ],
                    "/reviews": [ScriptedResponse(json=[{"id": "r3", "candidateId": "C3", "jobId": "J3"}])],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": "r3", "candidateId": "C3", "jobId": "J3"}]
        assert result.committed_states[:2] == [
            SmartRecruitersResumeConfig(candidate_page_id="c2"),
            SmartRecruitersResumeConfig(candidate_page_id="c3"),
        ]

    @parameterized.expand([(301,), (302,)])
    def test_does_not_follow_a_redirect_with_the_api_key(self, status: int) -> None:
        result = _driver().run(
            "reviews",
            route(
                {
                    "/candidates": [
                        ScriptedResponse(status=status, headers={"Location": "https://elsewhere.example/candidates"})
                    ]
                }
            ),
        )

        assert result.rows == []
        assert len(result.requests) == 1
        assert isinstance(result.raised, ValueError)
        assert "refusing to follow" in str(result.raised)
