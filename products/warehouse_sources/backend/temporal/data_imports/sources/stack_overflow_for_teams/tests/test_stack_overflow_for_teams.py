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
    def test_auth_is_framework_bearer(self, MockSession) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
            BearerTokenAuth,
        )

        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "1"}], total_pages=1)])

        _rows(_source("Questions", _make_manager()))

        auth = snapshots[0]["auth"]
        assert isinstance(auth, BearerTokenAuth)
        assert auth.token == "tok"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_only_while_pages_remain(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "1"}], page=1, total_pages=2),
                _response([{"id": "2"}], page=2, total_pages=2),
            ],
        )

        manager = _make_manager()
        _rows(_source("Questions", manager))

        # State is saved only while more pages remain (page 1 -> next_page 2), never on the last page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == StackOverflowForTeamsResumeConfig(next_page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "2"}], page=2, total_pages=2)])

        rows = _rows(_source("Questions", _make_manager(StackOverflowForTeamsResumeConfig(next_page=2))))

        assert [r["id"] for r in rows] == ["2"]
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["page"] == 2

    @pytest.mark.parametrize(
        "endpoint, expected_path, expected_sort, expected_order",
        [
            ("Questions", "/questions", "creation", "asc"),
            ("Articles", "/articles", "creation", "asc"),
            ("Tags", "/tags", "creationDate", "asc"),
            ("Users", "/users", "reputation", "asc"),
            ("Collections", "/collections", "creation", "asc"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_each_top_level_endpoint_requests_its_own_path_and_sort(
        self, MockSession, endpoint, expected_path, expected_sort, expected_order
    ) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "1"}], total_pages=1)])

        _rows(_source(endpoint, _make_manager()))

        assert snapshots[0]["url"] == f"https://api.stackoverflowteams.com/v3/teams/engineering{expected_path}"
        assert snapshots[0]["params"]["sort"] == expected_sort
        assert snapshots[0]["params"]["order"] == expected_order

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], total_pages=1)])

        manager = _make_manager()
        rows = _rows(_source("Questions", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_items_key_stops_quietly(self, MockSession) -> None:
        # A body without the "items" key is treated as an empty page.
        session = MockSession.return_value
        _wire(session, [_response(None, drop_key=True)])

        rows = _rows(_source("Questions", _make_manager()))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_incremental_cursor_ever_passed(self, MockSession) -> None:
        # Every endpoint is full refresh - no server-side timestamp filter is used.
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "1"}], total_pages=1)])

        _rows(_source("Questions", _make_manager()))

        assert "from" not in snapshots[0]["params"]
        assert "to" not in snapshots[0]["params"]


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

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.stack_overflow_for_teams.build_dependent_resource"
    )
    def test_answers_fanout_wires_selectors(self, mock_build_dependent_resource) -> None:
        mock_build_dependent_resource.return_value = iter([])

        stack_overflow_for_teams_source(
            team="engineering",
            api_token="tok",
            endpoint="Answers",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["page_size_param"] == "pageSize"
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "items"
        assert kwargs["child_endpoint_extra"]["data_selector"] == "items"
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["fanout"].parent_name == "Questions"
        assert kwargs["fanout"].resolve_param == "questionId"
        assert kwargs["fanout"].resolve_field == "id"


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
    def test_unauthorized(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("engineering", "tok") == (False, 401)

    @mock.patch(SO4T_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("engineering", "tok") == (False, None)

    @mock.patch(SO4T_SESSION_PATCH)
    def test_probes_users_me_endpoint_with_bearer_header(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("engineering", "tok")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.stackoverflowteams.com/v3/teams/engineering/users/me"
        assert call.kwargs["headers"]["Authorization"] == "Bearer tok"

    @mock.patch(SO4T_SESSION_PATCH)
    def test_bad_team_raises_before_probe(self, mock_session) -> None:
        with pytest.raises(ValueError, match="Invalid Stack Overflow for Teams team name"):
            validate_credentials("team/../evil", "tok")
        mock_session.assert_not_called()
