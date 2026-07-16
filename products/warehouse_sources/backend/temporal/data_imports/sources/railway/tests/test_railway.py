from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.railway import railway
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.railway import (
    RailwayResumeConfig,
    RailwayRetryableError,
    get_rows,
    railway_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.source import RailwaySource

RAILWAY_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.railway.railway"


class FakeResumableSourceManager:
    def __init__(self, state: RailwayResumeConfig | None = None):
        self.state = state
        self.saved: list[RailwayResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> RailwayResumeConfig | None:
        return self.state

    def save_state(self, state: RailwayResumeConfig) -> None:
        self.saved.append(state)
        self.state = state


def _response(payload: dict[str, Any], status_code: int = 200, headers: dict[str, str] | None = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = payload
    response.headers = headers or {}
    response.text = ""
    return response


def _connection(path: tuple[str, ...], nodes: list[dict[str, Any]], end_cursor: str | None = None) -> dict[str, Any]:
    data: Any = {
        "edges": [{"node": node} for node in nodes],
        "pageInfo": {"hasNextPage": end_cursor is not None, "endCursor": end_cursor},
    }
    for key in reversed(path):
        data = {key: data}
    return {"data": data}


def _projects_page(ids: list[str], end_cursor: str | None = None) -> dict[str, Any]:
    return _connection(("projects",), [{"id": project_id} for project_id in ids], end_cursor)


def _run(
    endpoint: str,
    responses: list[dict[str, Any] | mock.MagicMock],
    manager: FakeResumableSourceManager | None = None,
    **kwargs: Any,
) -> tuple[list[list[dict[str, Any]]], mock.MagicMock, FakeResumableSourceManager]:
    manager = manager or FakeResumableSourceManager()
    session = mock.MagicMock()
    session.post.side_effect = [r if isinstance(r, mock.MagicMock) else _response(r) for r in responses]

    with mock.patch(f"{RAILWAY_MODULE}.make_tracked_session", return_value=session):
        batches = list(
            get_rows(
                api_token="token",
                endpoint=endpoint,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
                **kwargs,
            )
        )
    return batches, session, manager


def _request_variables(session: mock.MagicMock, call_index: int) -> dict[str, Any]:
    return session.post.call_args_list[call_index].kwargs["json"]["variables"]


class TestRailway:
    def test_projects_pagination_follows_cursor_and_saves_state_after_yield(self):
        batches, session, manager = _run(
            "projects",
            [
                _projects_page(["p1", "p2"], end_cursor="c1"),
                _projects_page(["p3"]),
            ],
        )

        assert [[row["id"] for row in batch] for batch in batches] == [["p1", "p2"], ["p3"]]
        assert _request_variables(session, 0)["after"] is None
        assert _request_variables(session, 1)["after"] == "c1"
        # State saved once (after the first page yielded) — never for the terminal page.
        assert [state.cursor for state in manager.saved] == ["c1"]

    def test_projects_resume_starts_from_saved_cursor(self):
        _, session, _ = _run(
            "projects",
            [_projects_page(["p3"])],
            manager=FakeResumableSourceManager(RailwayResumeConfig(cursor="c9")),
        )

        assert _request_variables(session, 0)["after"] == "c9"

    def test_fan_out_queries_each_project_and_bookmarks_the_next(self):
        batches, session, manager = _run(
            "services",
            [
                _projects_page(["p1", "p2"]),
                _connection(("project", "services"), [{"id": "s1", "projectId": "p1"}]),
                _connection(("project", "services"), [{"id": "s2", "projectId": "p2"}]),
            ],
        )

        assert [[row["id"] for row in batch] for batch in batches] == [["s1"], ["s2"]]
        assert _request_variables(session, 1)["projectId"] == "p1"
        assert _request_variables(session, 2)["projectId"] == "p2"
        # A crash between projects must resume at p2, not restart the whole fan-out.
        assert [(state.project_id, state.cursor) for state in manager.saved] == [("p2", None)]

    def test_fan_out_resume_skips_completed_projects_and_uses_saved_cursor(self):
        _, session, _ = _run(
            "services",
            [
                _projects_page(["p1", "p2", "p3"]),
                _connection(("project", "services"), [{"id": "s2b", "projectId": "p2"}]),
                _connection(("project", "services"), [{"id": "s3", "projectId": "p3"}]),
            ],
            manager=FakeResumableSourceManager(RailwayResumeConfig(cursor="c5", project_id="p2")),
        )

        first_child = _request_variables(session, 1)
        assert first_child["projectId"] == "p2"
        assert first_child["after"] == "c5"
        # p3 starts fresh — the saved cursor belongs to p2's connection only.
        assert _request_variables(session, 2)["after"] is None

    def test_fan_out_resume_with_deleted_bookmark_project_starts_over(self):
        batches, session, _ = _run(
            "services",
            [
                _projects_page(["p1"]),
                _connection(("project", "services"), [{"id": "s1", "projectId": "p1"}]),
            ],
            manager=FakeResumableSourceManager(RailwayResumeConfig(cursor="c5", project_id="gone")),
        )

        assert _request_variables(session, 1)["projectId"] == "p1"
        assert _request_variables(session, 1)["after"] is None

    def test_fan_out_skips_project_deleted_mid_sync(self):
        batches, _, _ = _run(
            "services",
            [
                _projects_page(["p1", "p2"]),
                {"data": {"project": None}},
                _connection(("project", "services"), [{"id": "s2", "projectId": "p2"}]),
            ],
        )

        assert [[row["id"] for row in batch] for batch in batches] == [["s2"]]

    def test_project_members_rows_carry_project_id(self):
        batches, _, _ = _run(
            "project_members",
            [
                _projects_page(["p1"]),
                {"data": {"projectMembers": [{"id": "u1", "email": "a@b.c", "role": "ADMIN"}]}},
            ],
        )

        assert batches == [[{"project_id": "p1", "id": "u1", "email": "a@b.c", "role": "ADMIN"}]]

    def test_deployments_incremental_stops_once_page_predates_watermark(self):
        deployments_path = ("deployments",)
        batches, session, _ = _run(
            "deployments",
            [
                _projects_page(["p1"]),
                _connection(
                    deployments_path,
                    [
                        {"id": "d1", "createdAt": "2024-07-01T00:00:00Z"},
                        {"id": "d2", "createdAt": "2024-06-15T00:00:00Z"},
                    ],
                    end_cursor="c1",
                ),
                _connection(
                    deployments_path,
                    [
                        {"id": "d3", "createdAt": "2024-05-01T00:00:00Z"},
                        {"id": "d4", "createdAt": "2024-04-01T00:00:00Z"},
                    ],
                    end_cursor="c2",
                ),
                # A third page exists server-side but must never be requested.
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 6, 1, tzinfo=UTC),
            incremental_field="createdAt",
        )

        # Both pages yielded (the boundary page merges/dedupes), but pagination stops there.
        assert [[row["id"] for row in batch] for batch in batches] == [["d1", "d2"], ["d3", "d4"]]
        assert session.post.call_count == 3

    def test_deployments_full_history_walked_when_no_watermark(self):
        deployments_path = ("deployments",)
        batches, session, _ = _run(
            "deployments",
            [
                _projects_page(["p1"]),
                _connection(deployments_path, [{"id": "d1", "createdAt": "2024-07-01T00:00:00Z"}], end_cursor="c1"),
                _connection(deployments_path, [{"id": "d2", "createdAt": "2024-04-01T00:00:00Z"}]),
            ],
        )

        assert [[row["id"] for row in batch] for batch in batches] == [["d1"], ["d2"]]
        assert session.post.call_count == 3

    def test_not_authorized_error_matches_non_retryable_catalog(self):
        with pytest.raises(Exception) as exc_info:
            _run("projects", [{"errors": [{"message": "Not Authorized"}], "data": None}])

        non_retryable = RailwaySource().get_non_retryable_errors()
        assert any(key in str(exc_info.value) for key in non_retryable)

    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_status_codes(self, status_code):
        session = mock.MagicMock()
        session.post.return_value = _response({}, status_code=status_code)

        with pytest.raises(RailwayRetryableError):
            railway._execute.__wrapped__(session, {}, "query {}", {}, mock.MagicMock())

    def test_source_response_shape_per_endpoint(self):
        manager = FakeResumableSourceManager()

        deployments = railway_source("token", "deployments", mock.MagicMock(), manager)  # type: ignore[arg-type]
        assert deployments.primary_keys == ["id"]
        assert deployments.sort_mode == "desc"
        assert deployments.partition_mode == "datetime"
        assert deployments.partition_keys == ["createdAt"]

        members = railway_source("token", "project_members", mock.MagicMock(), manager)  # type: ignore[arg-type]
        # Member ids repeat across projects — dropping the composite key would seed duplicate
        # rows that every later merge multi-matches.
        assert members.primary_keys == ["project_id", "id"]
        assert members.partition_mode is None

    @parameterized.expand(
        [
            ({"data": {"projects": {"edges": []}}}, True, None),
            ({"errors": [{"message": "Not Authorized"}], "data": None}, False, "token"),
            ({"errors": [{"message": "Something else"}], "data": None}, False, "Something else"),
        ]
    )
    def test_validate_credentials(self, payload, expected_valid, expected_message_contains):
        session = mock.MagicMock()
        session.post.return_value = _response(payload)

        with mock.patch(f"{RAILWAY_MODULE}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials("token")

        assert is_valid is expected_valid
        if expected_message_contains is None:
            assert message is None
        else:
            assert message is not None and expected_message_contains in message

    def test_validate_credentials_network_error_returns_invalid(self):
        session = mock.MagicMock()
        session.post.side_effect = ConnectionError("boom")

        with mock.patch(f"{RAILWAY_MODULE}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials("token")

        assert is_valid is False
        assert message is not None
