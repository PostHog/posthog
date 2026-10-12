import json
from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.settings import (
    STACK_OVERFLOW_FOR_TEAMS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.stack_overflow_for_teams import (
    StackOverflowForTeamsResumeConfig,
    normalize_team,
    stack_overflow_for_teams_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the stack_overflow_for_teams module.
SO4T_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.stack_overflow_for_teams.make_tracked_session"
# The fan-out helper builds resources via rest_api_resources in the fanout module.
FANOUT_RESOURCES_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
)


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


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
    items: list[dict[str, Any]] | None,
    *,
    page: int | None = None,
    total_pages: int | None = None,
    drop_key: bool = False,
) -> Response:
    body: dict[str, Any] = {}
    if not drop_key:
        body["items"] = items or []
    if page is not None:
        body["page"] = page
    if total_pages is not None:
        body["totalPages"] = total_pages
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: StackOverflowForTeamsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state - snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return stack_overflow_for_teams_source(
        team="engineering",
        api_token="tok",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestStackOverflowForTeamsSourceNonFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_total_pages(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "1"}, {"id": "2"}], page=1, total_pages=2),
                _response([{"id": "3"}], page=2, total_pages=2),
            ],
        )

        rows = _rows(_source("Questions", _make_manager()))

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        # totalPages=2 terminates after the last page - no extra empty-page request.
        assert session.send.call_count == 2
        assert snapshots[0]["url"] == "https://api.stackoverflowteams.com/v3/teams/engineering/questions"
        assert snapshots[0]["params"] == {"pageSize": 100, "sort": "creation", "order": "asc", "page": 1}
        assert snapshots[1]["params"]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "2"}], page=2, total_pages=2)])

        rows = _rows(_source("Questions", _make_manager(StackOverflowForTeamsResumeConfig(next_page=2))))

        assert [r["id"] for r in rows] == ["2"]
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["page"] == 2


class TestStackOverflowForTeamsSourceFanout:
    @mock.patch(FANOUT_RESOURCES_PATCH)
    def test_answers_fanout_row_format(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("Questions", [{"id": "q1"}]),
            _FakeDltResource("Answers", [{"id": "a1", "questionId": "q1"}]),
        ]

        response = stack_overflow_for_teams_source(
            team="engineering",
            api_token="tok",
            endpoint="Answers",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )

        rows = list(cast(Any, response.items()))
        assert rows == [{"id": "a1", "questionId": "q1"}]
        assert response.primary_keys == ["id", "questionId"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["creationDate"]


class TestExpectedSchemaEndpoints:
    def test_every_endpoint_declared_in_settings_has_a_path_and_primary_key(self) -> None:
        for _name, config in STACK_OVERFLOW_FOR_TEAMS_ENDPOINTS.items():
            assert config.path
            assert config.primary_keys


class TestValidateCredentials:
    @mock.patch(SO4T_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("engineering", "tok") == (True, 200)

    @mock.patch(SO4T_SESSION_PATCH)
    def test_bad_team_raises_before_probe(self, mock_session) -> None:
        with pytest.raises(ValueError, match="Invalid Stack Overflow for Teams team name"):
            validate_credentials("team/../evil", "tok")
        mock_session.assert_not_called()
