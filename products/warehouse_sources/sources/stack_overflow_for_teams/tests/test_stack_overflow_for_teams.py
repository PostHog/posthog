from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, route, scripted_network
from products.warehouse_sources.sources.stack_overflow_for_teams._config import StackOverflowForTeamsSourceConfig
from products.warehouse_sources.sources.stack_overflow_for_teams.settings import STACK_OVERFLOW_FOR_TEAMS_ENDPOINTS
from products.warehouse_sources.sources.stack_overflow_for_teams.source import StackOverflowForTeamsSource
from products.warehouse_sources.sources.stack_overflow_for_teams.stack_overflow_for_teams import (
    StackOverflowForTeamsResumeConfig,
    normalize_team,
    validate_credentials,
)


class TestNormalizeTeam:
    @parameterized.expand(
        [
            ("bare", "engineering", "engineering"),
            ("with_hyphen", "team-alpha", "team-alpha"),
            ("with_underscore", "team_alpha", "team_alpha"),
            ("whitespace", "  engineering  ", "engineering"),
            ("alnum", "team123", "team123"),
        ]
    )
    def test_valid_teams(self, _name: str, value: str, expected: str) -> None:
        assert normalize_team(value) == expected

    @parameterized.expand(
        [
            ("path_injection", "team/../evil"),
            ("host_injection", "team.evil.com"),
            ("userinfo_injection", "team@evil.com"),
            ("query_injection", "team?x=1"),
            ("empty", ""),
            ("space_inside", "team one"),
        ]
    )
    def test_invalid_teams_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_team(value)


def _response(
    items: list[dict[str, Any]],
    *,
    page: int | None = None,
    total_pages: int | None = None,
) -> ScriptedResponse:
    body: dict[str, Any] = {"items": items}
    if page is not None:
        body["page"] = page
    if total_pages is not None:
        body["totalPages"] = total_pages
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(
        StackOverflowForTeamsSource(), StackOverflowForTeamsSourceConfig(team="engineering", api_token="tok")
    )


class TestStackOverflowForTeamsSourceNonFanout:
    def test_paginates_until_total_pages(self) -> None:
        result = _driver().run(
            "Questions",
            [
                _response([{"id": "1"}, {"id": "2"}], page=1, total_pages=2),
                _response([{"id": "3"}], page=2, total_pages=2),
            ],
        )

        assert [r["id"] for r in result.rows] == ["1", "2", "3"]
        # totalPages=2 terminates after the last page - no extra empty-page request.
        assert len(result.requests) == 2
        assert result.requests[0].url.startswith("https://api.stackoverflowteams.com/v3/teams/engineering/questions")
        assert result.queries[0] == {"pageSize": ("100",), "sort": ("creation",), "order": ("asc",), "page": ("1",)}
        assert result.params("page") == ["1", "2"]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "Questions",
            [_response([{"id": "2"}], page=2, total_pages=2)],
            resume_state=StackOverflowForTeamsResumeConfig(next_page=2),
        )

        assert [r["id"] for r in result.rows] == ["2"]
        assert len(result.requests) == 1
        assert result.params("page") == ["2"]


class TestStackOverflowForTeamsSourceFanout:
    def test_answers_fanout_row_format(self) -> None:
        result = _driver().run(
            "Answers",
            route(
                {
                    "/v3/teams/engineering/questions": [_response([{"id": "q1"}], page=1, total_pages=1)],
                    "/v3/teams/engineering/questions/q1/answers": [
                        _response([{"id": "a1", "questionId": "q1"}], page=1, total_pages=1)
                    ],
                }
            ),
        )

        assert result.rows == [{"id": "a1", "questionId": "q1"}]
        assert result.response is not None
        assert result.response.primary_keys == ["id", "questionId"]
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["creationDate"]


_TEAM = "/v3/teams/engineering"


class TestStackOverflowForTeamsSourceSinglePageFanout:
    @parameterized.expand(
        [
            (
                "question_comments_skip_questions_without_comments",
                "QuestionComments",
                {
                    f"{_TEAM}/questions": [
                        _response([{"id": 1, "commentCount": 2}, {"id": 2, "commentCount": 0}], total_pages=1)
                    ],
                    f"{_TEAM}/questions/1/comments": [ScriptedResponse(json=[{"id": 10}, {"id": 11}])],
                },
                [{"id": 10, "questionId": 1}, {"id": 11, "questionId": 1}],
            ),
            (
                "question_comments_ignore_deleted_question",
                "QuestionComments",
                {
                    f"{_TEAM}/questions": [_response([{"id": 1, "commentCount": 1}], total_pages=1)],
                    f"{_TEAM}/questions/1/comments": [ScriptedResponse(status=404, json={"title": "Not Found"})],
                },
                [],
            ),
            (
                "experts_explode_users_and_groups_and_skip_tags_without_experts",
                "TagSubjectMatterExperts",
                {
                    f"{_TEAM}/tags": [
                        _response(
                            [
                                {"id": 5, "subjectMatterExpertCount": 3},
                                {"id": 6, "subjectMatterExpertCount": 0},
                                {"id": 7, "subjectMatterExpertCount": None},
                            ],
                            total_pages=1,
                        )
                    ],
                    f"{_TEAM}/tags/5/subject-matter-experts": [
                        ScriptedResponse(
                            json={
                                "users": [{"id": 1, "name": "Ada"}],
                                "userGroups": [{"id": 1, "name": "Platform", "users": [{"id": 2}]}],
                            }
                        )
                    ],
                },
                [
                    {"id": 1, "name": "Ada", "tagId": 5, "expertType": "user"},
                    {"id": 1, "name": "Platform", "users": [{"id": 2}], "tagId": 5, "expertType": "userGroup"},
                ],
            ),
            (
                "experts_ignore_feature_turned_off",
                "TagSubjectMatterExperts",
                {
                    f"{_TEAM}/tags": [_response([{"id": 5, "subjectMatterExpertCount": 1}], total_pages=1)],
                    f"{_TEAM}/tags/5/subject-matter-experts": [
                        ScriptedResponse(status=422, json={"title": "Subject matter experts feature not enabled"})
                    ],
                },
                [],
            ),
        ]
    )
    def test_fanout_rows(
        self,
        _name: str,
        endpoint: str,
        routes: dict[str, list[ScriptedResponse]],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = _driver().run(endpoint, route(routes))

        assert result.raised is None
        assert result.rows == expected_rows
        # Skipped parents send no child request, and the child takes no paging params.
        assert result.paths == list(routes)
        assert result.queries[0]["pageSize"] == ("100",)
        assert all(query == {} for query in result.queries[1:])


class TestStackOverflowForTeamsSourceAnswerComments:
    def test_walks_questions_then_answers_then_comments(self) -> None:
        result = _driver().run(
            "AnswerComments",
            route(
                {
                    f"{_TEAM}/questions": [
                        _response([{"id": 1, "answerCount": 3}, {"id": 2, "answerCount": 0}], total_pages=1)
                    ],
                    f"{_TEAM}/questions/1/answers": [
                        _response([{"id": 20, "questionId": 1, "commentCount": 1}], page=1, total_pages=2),
                        _response(
                            [{"id": 21, "questionId": 1, "commentCount": 0}, {"id": 22, "questionId": 1}],
                            page=2,
                            total_pages=2,
                        ),
                    ],
                    f"{_TEAM}/questions/1/answers/20/comments": [ScriptedResponse(json=[{"id": 30}])],
                    f"{_TEAM}/questions/1/answers/22/comments": [ScriptedResponse(json=[{"id": 31}])],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {"id": 30, "answerId": 20, "questionId": 1},
            {"id": 31, "answerId": 22, "questionId": 1},
        ]
        assert result.paths == [
            f"{_TEAM}/questions",
            f"{_TEAM}/questions/1/answers",
            f"{_TEAM}/questions/1/answers/20/comments",
            f"{_TEAM}/questions/1/answers",
            f"{_TEAM}/questions/1/answers/22/comments",
        ]
        assert result.params("page") == ["1", "1", None, "2", None]


class TestExpectedSchemaEndpoints:
    def test_every_endpoint_declared_in_settings_has_a_path_and_primary_key(self) -> None:
        for _name, config in STACK_OVERFLOW_FOR_TEAMS_ENDPOINTS.items():
            assert config.path
            assert config.primary_keys


class TestValidateCredentials:
    def test_bad_team_raises_before_probe(self) -> None:
        with scripted_network([]) as network:
            with pytest.raises(ValueError, match="Invalid Stack Overflow for Teams team name"):
                validate_credentials("team/../evil", "tok")
        assert network.requests_log == []
