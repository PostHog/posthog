from collections.abc import Callable
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.motion import MotionSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.motion.motion import (
    MotionResumeConfig,
    motion_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.motion.source import MotionSource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.motion.motion"


def _manager(resume_state: MotionResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(key: str, rows: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={key: rows, "meta": {"nextCursor": next_cursor} if next_cursor else {}})


_Pages = dict[tuple[str, str | None, str | None], ScriptedResponse]


def _vendor(pages: _Pages) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        parent_id = request.param("workspaceId") or request.param("taskId")
        return pages[(request.path, parent_id, request.param("cursor"))]

    return respond


_WORKSPACE_PAGES: _Pages = {
    ("/v1/workspaces", None, None): _page("workspaces", [{"id": "ws-1"}], next_cursor="ws-page-2"),
    ("/v1/workspaces", None, "ws-page-2"): _page("workspaces", [{"id": "ws-2"}]),
}

_RECURRING_TASK_PAGES: _Pages = {
    **_WORKSPACE_PAGES,
    ("/v1/recurring-tasks", "ws-1", None): _page("tasks", [{"id": "rt-1"}], next_cursor="rt-page-2"),
    ("/v1/recurring-tasks", "ws-1", "rt-page-2"): _page("tasks", [{"id": "rt-2"}]),
    ("/v1/recurring-tasks", "ws-2", None): _page("tasks", [{"id": "rt-3"}]),
}


class TestMotionSource:
    def test_a_saved_cursor_seeds_the_paginator(self) -> None:
        result = SourceDriver(MotionSource(), MotionSourceConfig(api_key="key")).run(
            "tasks",
            [ScriptedResponse(json={"tasks": [{"id": "task-2"}], "meta": {}})],
            resume_state=MotionResumeConfig(cursor="page-2"),
        )

        assert result.raised is None
        assert result.params("cursor") == ["page-2"]
        assert result.rows == [{"id": "task-2"}]

    @pytest.mark.parametrize(
        "state,expected_saves,expected_clears",
        [
            ({"cursor": "next-page"}, [mock.call(MotionResumeConfig(cursor="next-page"))], 0),
            ({}, [], 0),
            (None, [], 1),
        ],
    )
    def test_checkpoint_lifecycle(
        self,
        state: Optional[dict[str, Any]],
        expected_saves: list,
        expected_clears: int,
    ) -> None:
        manager = _manager()
        resource = mock.MagicMock()
        resource.name = "tasks"
        with mock.patch(f"{_MODULE}.rest_api_resources", return_value=[resource]) as rest_api_resources:
            motion_source("key", "tasks", 1, "job", manager)

        rest_api_resources.call_args.kwargs["resume_hook"](state)
        assert manager.save_state.call_args_list == expected_saves
        assert manager.clear_state.call_count == expected_clears


class TestMotionFanout:
    @pytest.mark.parametrize(
        "endpoint,pages,expected_rows",
        [
            (
                "recurring_tasks",
                _RECURRING_TASK_PAGES,
                [
                    {"id": "rt-1", "workspaceId": "ws-1"},
                    {"id": "rt-2", "workspaceId": "ws-1"},
                    {"id": "rt-3", "workspaceId": "ws-2"},
                ],
            ),
            (
                "custom_fields",
                {
                    **_WORKSPACE_PAGES,
                    ("/beta/workspaces/ws-1/custom-fields", None, None): ScriptedResponse(
                        json=[{"id": "cf-1", "field": "text"}, {"id": "cf-2", "field": "select"}]
                    ),
                    ("/beta/workspaces/ws-2/custom-fields", None, None): ScriptedResponse(json=[]),
                },
                [
                    {"id": "cf-1", "field": "text", "workspaceId": "ws-1"},
                    {"id": "cf-2", "field": "select", "workspaceId": "ws-1"},
                ],
            ),
            (
                "comments",
                {
                    ("/v1/tasks", None, None): _page("tasks", [{"id": "t-1"}, {"id": "t-2"}, {"id": "t-3"}]),
                    ("/v1/comments", "t-1", None): _page(
                        "comments", [{"id": "c-1", "taskId": "t-1"}], next_cursor="c-page-2"
                    ),
                    ("/v1/comments", "t-1", "c-page-2"): _page("comments", [{"id": "c-2", "taskId": "t-1"}]),
                    # The task was deleted after the task list was read.
                    ("/v1/comments", "t-2", None): ScriptedResponse(status=404, json={"message": "Not found"}),
                    ("/v1/comments", "t-3", None): _page("comments", [{"id": "c-1", "taskId": "t-3"}]),
                },
                [
                    {"id": "c-1", "taskId": "t-1"},
                    {"id": "c-2", "taskId": "t-1"},
                    {"id": "c-1", "taskId": "t-3"},
                ],
            ),
        ],
    )
    def test_walks_every_parent_and_child_page(
        self,
        endpoint: str,
        pages: _Pages,
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = SourceDriver(MotionSource(), MotionSourceConfig(api_key="key")).run(endpoint, _vendor(pages))

        assert result.raised is None
        assert result.rows == expected_rows
        assert len(result.requests) == len(pages)
        assert result.saved_states
        assert all(state.fanout_state is not None for state in result.saved_states)
        # Fan-out progress must not outlive a finished run, or the next sync would skip every parent.
        assert result.completed_state is None

    def test_comments_cover_tasks_in_every_status(self) -> None:
        pages: _Pages = {
            ("/v1/tasks", None, None): _page("tasks", [{"id": "t-1"}]),
            ("/v1/comments", "t-1", None): _page("comments", []),
        }

        result = SourceDriver(MotionSource(), MotionSourceConfig(api_key="key")).run("comments", _vendor(pages))

        assert result.raised is None
        assert [request.param("includeAllStatuses") for request in result.requests if request.path == "/v1/tasks"] == [
            "true"
        ]

    @pytest.mark.parametrize(
        "fanout_state,expected_child_requests",
        [
            (
                {"completed": ["/v1/recurring-tasks?workspaceId=ws-1"], "current": None, "child_state": None},
                [("ws-2", None)],
            ),
            (
                {
                    "completed": [],
                    "current": "/v1/recurring-tasks?workspaceId=ws-1",
                    "child_state": {"cursor": "rt-page-2"},
                },
                [("ws-1", "rt-page-2"), ("ws-2", None)],
            ),
        ],
    )
    def test_a_saved_fanout_state_skips_finished_parents(
        self,
        fanout_state: dict[str, Any],
        expected_child_requests: list[tuple[str, str | None]],
    ) -> None:
        result = SourceDriver(MotionSource(), MotionSourceConfig(api_key="key")).run(
            "recurring_tasks",
            _vendor(_RECURRING_TASK_PAGES),
            resume_state=MotionResumeConfig(fanout_state=fanout_state),
        )

        assert result.raised is None
        assert [
            (request.param("workspaceId"), request.param("cursor"))
            for request in result.requests
            if request.path == "/v1/recurring-tasks"
        ] == expected_child_requests


class TestMotionCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_valid",
        [(429, False)],
    )
    def test_status_maps_to_a_verdict(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, message = validate_credentials("key")

        assert valid is expected_valid
        assert (message is None) is expected_valid
        assert {request.path for request in network.requests_log} == {"/v1/workspaces"}
        assert all(request.headers["x-api-key"] == "key" for request in network.requests_log)

    def test_an_unreachable_api_is_reported_rather_than_raised(self) -> None:
        with scripted_network(always(ConnectionError("no route"))) as network:
            valid, message = validate_credentials("key")

        assert valid is False
        assert message is not None
        assert {request.path for request in network.requests_log} == {"/v1/workspaces"}
