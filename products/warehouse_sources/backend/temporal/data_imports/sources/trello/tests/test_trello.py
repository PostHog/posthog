import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.trello.settings import TRELLO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello import (
    TrelloResumeConfig,
    _add_created_at,
    _format_incremental_value,
    _get_headers,
    _id_to_created_at,
    trello_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the trello module.
TRELLO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello.make_tracked_session"
)


def _response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(*, can_resume: bool = False, resume_state: TrelloResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[tuple[Any, dict[str, Any]]]:
    """Wire a mock session and capture each request's (url, params) AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[tuple[Any, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append((request.url, dict(request.params or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return trello_source(
        api_key="key",
        api_token="token",
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestIdToCreatedAt:
    @parameterized.expand(
        [
            # 0x5abbe394 = 1522242964 = 2018-03-28T18:48:52+00:00
            ("valid_object_id", "5abbe394c78f17ffa9e10843", "2018-03-28T18:48:52+00:00"),
            ("too_short", "abc", None),
            ("non_hex_prefix", "zzzzzzzzc78f17ffa9e10843", None),
            ("not_a_string", 12345, None),
            ("none", None, None),
        ]
    )
    def test_id_to_created_at(self, _name: str, obj_id: Any, expected: str | None) -> None:
        assert _id_to_created_at(obj_id) == expected


class TestAddCreatedAt:
    def test_injects_created_at_from_id(self) -> None:
        item = _add_created_at({"id": "5abbe394c78f17ffa9e10843", "name": "Board"})
        assert item["created_at"] == "2018-03-28T18:48:52+00:00"

    def test_preserves_existing_created_at(self) -> None:
        item = _add_created_at({"id": "5abbe394c78f17ffa9e10843", "created_at": "already"})
        assert item["created_at"] == "already"

    def test_no_id_leaves_item_unchanged(self) -> None:
        item = _add_created_at({"name": "no id"})
        assert "created_at" not in item


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC), "2026-01-15T10:00:00+00:00"),
            ("naive_datetime", datetime(2026, 1, 15, 10, 0, 0), "2026-01-15T10:00:00+00:00"),
            ("date", date(2026, 1, 15), "2026-01-15T00:00:00+00:00"),
            ("string_passthrough", "2026-01-15T10:00:00Z", "2026-01-15T10:00:00Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestGetHeaders:
    def test_oauth_header_keeps_token_out_of_url(self) -> None:
        headers = _get_headers("my-key", "my-token")
        assert headers["Authorization"] == 'OAuth oauth_consumer_key="my-key", oauth_token="my-token"'


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("missing_token", 400, False, "Invalid Trello API key or token"),
            ("invalid_key", 401, False, "Invalid Trello API key or token"),
            ("forbidden", 403, False, "Your Trello token does not have the required permissions"),
        ]
    )
    def test_status_codes(self, _name: str, status: int, valid: bool, message: str | None) -> None:
        with mock.patch(TRELLO_SESSION_PATCH) as session:
            session.return_value.get.return_value = mock.MagicMock(status_code=status)
            result_valid, result_message = validate_credentials("key", "token")

        assert result_valid is valid
        assert result_message == message

    def test_request_exception(self) -> None:
        with mock.patch(TRELLO_SESSION_PATCH) as session:
            session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
            valid, message = validate_credentials("key", "token")

        assert valid is False
        assert message is not None
        assert "boom" in message

    def test_sends_oauth_header(self) -> None:
        with mock.patch(TRELLO_SESSION_PATCH) as session:
            session.return_value.get.return_value = mock.MagicMock(status_code=200)
            validate_credentials("my-key", "my-token")

        headers = session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == 'OAuth oauth_consumer_key="my-key", oauth_token="my-token"'


class TestMemberEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_boards_single_request_injects_created_at(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        boards = [{"id": "5abbe394c78f17ffa9e10843", "name": "A"}, {"id": "5abbe395c78f17ffa9e10843", "name": "B"}]
        snapshots = _wire(session, [_response(boards)])

        manager = _make_manager()
        rows = _rows(_source("boards", manager))

        assert [r["name"] for r in rows] == ["A", "B"]
        assert all("created_at" in r for r in rows)
        # Member endpoints are a single request; no resume checkpoints.
        manager.save_state.assert_not_called()
        url, params = snapshots[0]
        assert url == "https://api.trello.com/1/members/me/boards"
        assert params["limit"] == 1000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_fails_loud(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "nope"})])

        # A 200 whose body isn't a list means the response shape changed — fail loud rather than
        # wrapping the stray object as a single row.
        with pytest.raises(ValueError, match="list response body"):
            _rows(_source("organizations", _make_manager()))


class TestBoardFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_lists_fan_out_across_boards(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "board1"}, {"id": "board2"}]),
                _response([{"id": "l1"}]),
                _response([{"id": "l2"}, {"id": "l3"}]),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("lists", manager))

        assert [r["id"] for r in rows] == ["l1", "l2", "l3"]
        urls = [url for url, _ in snapshots]
        assert urls[0] == "https://api.trello.com/1/members/me/boards"
        assert snapshots[0][1] == {"fields": "id"}
        assert urls[1] == "https://api.trello.com/1/boards/board1/lists"
        assert urls[2] == "https://api.trello.com/1/boards/board2/lists"
        # Each completed board is checkpointed; the final state records both boards done.
        final_state = manager.save_state.call_args_list[-1].args[0].fanout_state
        assert final_state["completed"] == [
            "/boards/board1/lists",
            "/boards/board2/lists",
        ]
        assert final_state["current"] is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_boards(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "board1"}, {"id": "board2"}]),
                _response([{"id": "l2"}]),
            ],
        )

        manager = _make_manager(
            can_resume=True,
            resume_state=TrelloResumeConfig(
                fanout_state={"completed": ["/boards/board1/lists"], "current": None, "child_state": None}
            ),
        )
        rows = _rows(_source("lists", manager))

        # Only board2 is synced; board1 was already completed and is skipped.
        assert [r["id"] for r in rows] == ["l2"]
        urls = [url for url, _ in snapshots]
        assert not any("/boards/board1/" in u for u in urls)
        assert any(u.endswith("/boards/board2/lists") for u in urls)


class TestActionsIncremental:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_sends_since_and_limit(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "b1"}]),
                _response([{"id": "a1", "date": "2026-02-01T00:00:00Z"}]),
            ],
        )
        cutoff = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)

        _rows(_source("actions", _make_manager(), db_incremental_field_last_value=cutoff))

        actions_url, actions_params = snapshots[1]
        assert actions_url == "https://api.trello.com/1/boards/b1/actions"
        assert actions_params["since"] == "2026-01-15T10:00:00+00:00"
        assert actions_params["limit"] == 1000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_omits_since(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "b1"}]), _response([{"id": "a1"}])])

        _rows(_source("actions", _make_manager()))

        assert "since" not in snapshots[1][1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_with_before_cursor(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "b1"}]),
                _response([{"id": "a1"}, {"id": "a2"}]),  # full page (limit 2) → keep paging
                _response([{"id": "a3"}]),  # short page → stop
            ],
        )

        manager = _make_manager()
        # Drive pagination with a small page size instead of 1000 rows.
        with mock.patch.object(TRELLO_ENDPOINTS["actions"], "page_size", 2):
            rows = _rows(_source("actions", manager))

        assert [r["id"] for r in rows] == ["a1", "a2", "a3"]
        # First actions page carries no cursor; the second pages back with before=<oldest of page 1>.
        assert "before" not in snapshots[1][1]
        assert snapshots[2][1]["before"] == "a2"
        # Board fully drained → final checkpoint records it completed, nothing in progress.
        final_state = manager.save_state.call_args_list[-1].args[0].fanout_state
        assert final_state["completed"] == ["/boards/b1/actions"]
        assert final_state["current"] is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_uses_before_cursor(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "b1"}]), _response([{"id": "a1"}])])

        manager = _make_manager(
            can_resume=True,
            resume_state=TrelloResumeConfig(
                fanout_state={
                    "completed": [],
                    "current": "/boards/b1/actions",
                    "child_state": {"before": "oldest"},
                }
            ),
        )
        _rows(_source("actions", manager))

        assert snapshots[1][1]["before"] == "oldest"


class TestRetryClassification:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rate_limited_status_is_retried(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        boards = [{"id": "5abbe394c78f17ffa9e10843"}]
        _wire(session, [_response({}, status=429), _response(boards)])

        rows = _rows(_source("boards", _make_manager()))

        # The 429 is retried and the retry (200) yields rows.
        assert [r["id"] for r in rows] == ["5abbe394c78f17ffa9e10843"]
        assert session.send.call_count == 2


class TestTrelloSourceResponse:
    @parameterized.expand(
        [
            ("boards", "asc", "id"),
            ("actions", "desc", "id"),
            ("cards", "asc", "id"),
        ]
    )
    def test_source_response_shape(self, endpoint: str, sort_mode: str, primary_key: str) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.sort_mode == sort_mode
        assert response.primary_keys == [primary_key]
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"

    @parameterized.expand([(name,) for name in TRELLO_ENDPOINTS])
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        assert callable(response.items)
        assert response.primary_keys == [TRELLO_ENDPOINTS[endpoint].primary_key]
