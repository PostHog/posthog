from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.ashby import (
    ASHBY_BASE_URL,
    AUTH_ERROR_HINT,
    AshbyAPIError,
    AshbyResumeConfig,
    _errors_from_payload,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.source import AshbySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ashby import AshbySourceConfig


def _page(items: list[dict[str, Any]], *, more: bool = False, next_cursor: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"success": True, "results": items, "moreDataAvailable": more}
    if next_cursor is not None:
        body["nextCursor"] = next_cursor
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(AshbySource(), AshbySourceConfig(api_key="dummy-key"))


class TestErrorsFromPayload:
    @pytest.mark.parametrize(
        "payload, expected",
        [
            ({"errors": ["a", "b"]}, ["a", "b"]),
            ({"errors": "single"}, ["single"]),
            ({"error": "legacy"}, ["legacy"]),
            ({"success": False}, []),
        ],
    )
    def test_errors_from_payload(self, payload: dict[str, Any], expected: list[Any]) -> None:
        assert _errors_from_payload(payload) == expected


class TestPagination:
    def test_paginates_until_no_more_data(self) -> None:
        result = _driver().run(
            "candidates",
            [_page([{"id": "1"}], more=True, next_cursor="c1"), _page([{"id": "2"}])],
        )

        assert result.raised is None
        assert result.rows == [{"id": "1"}, {"id": "2"}]
        # First call has no cursor, second forwards nextCursor; limit is sent in the JSON body.
        assert "cursor" not in result.requests[0].json()
        assert result.requests[1].json()["cursor"] == "c1"
        assert result.requests[0].json()["limit"] == 100
        assert result.urls[0] == f"{ASHBY_BASE_URL}/candidate.list"
        assert result.requests[0].method == "POST"
        # Ashby authenticates via HTTP Basic: API key as username, empty password.
        assert result.requests[0].headers["authorization"] == "Basic ZHVtbXkta2V5Og=="

    def test_saves_state_after_yielding_each_page(self) -> None:
        result = _driver().run(
            "candidates",
            [_page([{"id": "1"}], more=True, next_cursor="c1"), _page([{"id": "2"}])],
        )
        assert result.raised is None
        assert result.saved_states == [AshbyResumeConfig(cursor="c1")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "candidates",
            [_page([{"id": "9"}])],
            resume_state=AshbyResumeConfig(cursor="resume-cursor"),
        )
        assert result.raised is None
        assert result.rows == [{"id": "9"}]
        assert result.requests[0].json()["cursor"] == "resume-cursor"

    def test_stops_when_more_data_unavailable_even_with_cursor(self) -> None:
        # Ashby can return a nextCursor alongside moreDataAvailable=false — that must terminate.
        result = _driver().run("candidates", [_page([{"id": "1"}], next_cursor="c9")])
        assert result.raised is None
        assert result.rows == [{"id": "1"}]
        assert len(result.requests) == 1
        assert result.saved_states == []

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_http_auth_errors_raise_matchable_error(self, status_code: int) -> None:
        result = _driver().run("candidates", [ScriptedResponse(status=status_code, json={})])
        assert isinstance(result.raised, requests.HTTPError)
        assert f"{status_code} Client Error" in str(result.raised)

    def test_success_false_auth_error_raises_matchable_api_error(self) -> None:
        result = _driver().run(
            "candidates",
            [ScriptedResponse(json={"success": False, "errors": ["Missing permission: candidatesRead"]})],
        )
        assert isinstance(result.raised, AshbyAPIError)
        assert AUTH_ERROR_HINT in str(result.raised)
        assert "Missing permission: candidatesRead" in str(result.raised)

    def test_success_false_non_auth_error_raises_without_auth_hint(self) -> None:
        result = _driver().run(
            "candidates", [ScriptedResponse(json={"success": False, "errors": ["validation failed"]})]
        )
        assert isinstance(result.raised, AshbyAPIError)
        assert AUTH_ERROR_HINT not in str(result.raised)
        assert "validation failed" in str(result.raised)


class TestCheckAccess:
    @pytest.mark.parametrize(
        "response, expected_status",
        [
            (ScriptedResponse(json={"success": True, "results": []}), 200),
            (ScriptedResponse(status=401), 401),
            (ScriptedResponse(status=403), 403),
            (ScriptedResponse(json={"success": False, "errors": ["Missing permission"]}), 403),
            (ScriptedResponse(json={"success": False, "errors": ["bad request"]}), 400),
            (ScriptedResponse(status=500), 500),
            (ScriptedResponse(body=b"not json"), 0),
        ],
    )
    def test_status_mapping(self, response: ScriptedResponse, expected_status: int) -> None:
        with scripted_network([response]):
            status, _message = check_access("k", "department.list")
        assert status == expected_status

    def test_probes_endpoint_with_basic_auth(self) -> None:
        with scripted_network([_page([])]) as network:
            check_access("k", "department.list")
        request = network.requests_log[0]
        assert request.url == f"{ASHBY_BASE_URL}/department.list"
        assert request.headers["authorization"] == "Basic azo="
        assert request.json() == {"limit": 1}

    def test_connection_error_returns_zero(self) -> None:
        with scripted_network([ConnectionResetError("boom")]):
            status, message = check_access("k", "department.list")
        assert status == 0
        assert message is not None


class TestFanOut:
    @pytest.mark.parametrize(
        "endpoint, parent_path, child_path, parent_id_field",
        [
            ("application_history", "application.list", "application.listHistory", "applicationId"),
            ("candidate_notes", "candidate.list", "candidate.listNotes", "candidateId"),
        ],
    )
    def test_calls_the_child_once_per_parent_and_injects_the_parent_id(
        self, endpoint: str, parent_path: str, child_path: str, parent_id_field: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _page([{"id": "parent-1"}, {"id": "parent-2"}]),
                _page([{"id": "child-1"}]),
                _page([{"id": "child-2"}]),
            ],
        )
        assert result.raised is None
        # The child rows carry no parent id, so the fan-out has to add it — without it the table
        # can't be joined back to its parent and its key isn't unique.
        assert result.rows == [
            {"id": "child-1", parent_id_field: "parent-1"},
            {"id": "child-2", parent_id_field: "parent-2"},
        ]
        assert result.urls == [
            f"{ASHBY_BASE_URL}/{parent_path}",
            f"{ASHBY_BASE_URL}/{child_path}",
            f"{ASHBY_BASE_URL}/{child_path}",
        ]
        assert result.requests[1].json() == {parent_id_field: "parent-1", "limit": 100}
        assert result.requests[2].json() == {parent_id_field: "parent-2", "limit": 100}

    def test_unpaginated_child_sends_only_the_resolve_param(self) -> None:
        # interviewStage.list takes interviewPlanId and nothing else — Ashby rejects a `limit`.
        result = _driver().run(
            "interview_stages",
            [
                _page([{"id": "plan-1"}]),
                _page([{"id": "stage-1", "interviewPlanId": "plan-1"}]),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": "stage-1", "interviewPlanId": "plan-1"}]
        assert result.requests[1].json() == {"interviewPlanId": "plan-1"}

    def test_resumes_at_the_parent_that_was_in_progress(self) -> None:
        result = _driver().run(
            "application_history",
            [_page([{"id": "app-1"}, {"id": "app-2"}]), _page([{"id": "h-2"}])],
            resume_state=AshbyResumeConfig(parent_index=1, child_cursor="half-way"),
        )
        assert result.raised is None
        assert result.rows == [{"id": "h-2", "applicationId": "app-2"}]
        assert result.requests[1].json()["cursor"] == "half-way"

    def test_checkpoints_each_finished_parent_against_its_page_cursor(self) -> None:
        result = _driver().run(
            "application_history",
            [
                _page([{"id": "app-1"}], more=True, next_cursor="p2"),
                _page([{"id": "h-1"}]),
                _page([{"id": "app-2"}]),
                _page([{"id": "h-2"}]),
            ],
        )
        assert result.raised is None
        # The second parent is recorded against "p2" — the cursor that fetched the page it is on,
        # not the one that fetched the page before it.
        assert result.saved_states == [
            AshbyResumeConfig(parent_cursor=None, parent_index=1),
            AshbyResumeConfig(parent_cursor="p2", parent_index=1),
        ]


class TestUnpaginatedListing:
    @pytest.mark.parametrize(
        "endpoint, path",
        [
            ("interview_stage_groups", "interviewStageGroup.list"),
            ("application_hiring_team_roles", "applicationHiringTeamRole.list"),
        ],
    )
    def test_sends_an_empty_body(self, endpoint: str, path: str) -> None:
        # These methods accept no request-body keys, and Ashby rejects a `limit`.
        result = _driver().run(endpoint, [_page([{"id": "1", "title": "Screen"}])])
        assert result.raised is None
        assert result.rows == [{"id": "1", "title": "Screen"}]
        assert result.urls == [f"{ASHBY_BASE_URL}/{path}"]
        assert result.requests[0].json() == {}


class TestVariantListing:
    def test_lists_each_survey_type_in_turn(self) -> None:
        result = _driver().run(
            "survey_submissions",
            [
                _page([{"id": "s-1", "surveyType": "CandidateExperience"}], more=True, next_cursor="c1"),
                _page([{"id": "s-2", "surveyType": "CandidateExperience"}]),
                _page([]),
                _page([{"id": "s-3", "surveyType": "HiringManagerExperience"}]),
            ],
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["s-1", "s-2", "s-3"]
        assert all(url == f"{ASHBY_BASE_URL}/surveySubmission.list" for url in result.urls)
        assert [request.json() for request in result.requests] == [
            {"limit": 100, "surveyType": "CandidateExperience"},
            {"limit": 100, "surveyType": "CandidateExperience", "cursor": "c1"},
            {"limit": 100, "surveyType": "Questionnaire"},
            {"limit": 100, "surveyType": "HiringManagerExperience"},
        ]
        # The cursor of one survey type must never be sent with the next one.
        assert result.saved_states == [
            AshbyResumeConfig(cursor="c1", variant_index=0),
            AshbyResumeConfig(variant_index=1),
            AshbyResumeConfig(variant_index=2),
        ]

    @pytest.mark.parametrize(
        "resume_state, expected_bodies",
        [
            (
                AshbyResumeConfig(cursor="half-way", variant_index=1),
                [
                    {"limit": 100, "surveyType": "Questionnaire", "cursor": "half-way"},
                    {"limit": 100, "surveyType": "HiringManagerExperience"},
                ],
            ),
            (
                AshbyResumeConfig(variant_index=2),
                [{"limit": 100, "surveyType": "HiringManagerExperience"}],
            ),
        ],
    )
    def test_resumes_at_the_survey_type_in_progress(
        self, resume_state: AshbyResumeConfig, expected_bodies: list[dict[str, Any]]
    ) -> None:
        result = _driver().run(
            "survey_submissions",
            [_page([{"id": f"s-{index}"}]) for index in range(len(expected_bodies))],
            resume_state=resume_state,
        )
        assert result.raised is None
        assert [request.json() for request in result.requests] == expected_bodies


class TestNestedRows:
    def test_interview_events_are_read_from_the_schedule_listing(self) -> None:
        result = _driver().run(
            "interview_events",
            [
                _page(
                    [
                        {"id": "sched-1", "interviewEvents": [{"id": "ev-1"}, {"id": "ev-2"}]},
                        {"id": "sched-2", "interviewEvents": []},
                    ]
                )
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": "ev-1"}, {"id": "ev-2"}]
        assert result.urls[0] == f"{ASHBY_BASE_URL}/interviewSchedule.list"
