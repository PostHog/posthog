from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stackoverflowforteams import (
    StackOverflowForTeamsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.settings import (
    STACK_OVERFLOW_FOR_TEAMS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.source import (
    StackOverflowForTeamsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.stack_overflow_for_teams import (
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
