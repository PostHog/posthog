from datetime import UTC, datetime
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.railway import (
    RailwaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.railway import railway
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.railway import (
    RailwayResumeConfig,
    RailwayRetryableError,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.source import RailwaySource


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


def _run(endpoint: str, responses: list[dict[str, Any]], **inputs: Any) -> DriveResult:
    script: list[ScriptedResponse | BaseException] = [ScriptedResponse(json=payload) for payload in responses]
    return SourceDriver(RailwaySource(), RailwaySourceConfig(api_token="token")).run(endpoint, script, **inputs)


def _request_variables(result: DriveResult, call_index: int) -> dict[str, Any]:
    return result.requests[call_index].json()["variables"]


def _batch_ids(result: DriveResult) -> list[list[str]]:
    return [[row["id"] for row in batch] for batch in result.items]


class TestRailway:
    def test_projects_pagination_follows_cursor_and_saves_state_after_yield(self):
        result = _run(
            "projects",
            [
                _projects_page(["p1", "p2"], end_cursor="c1"),
                _projects_page(["p3"]),
            ],
        )

        assert _batch_ids(result) == [["p1", "p2"], ["p3"]]
        assert _request_variables(result, 0)["after"] is None
        assert _request_variables(result, 1)["after"] == "c1"
        # State saved once (after the first page yielded) — never for the terminal page.
        assert [state.cursor for state in result.saved_states] == ["c1"]

    def test_projects_resume_starts_from_saved_cursor(self):
        result = _run("projects", [_projects_page(["p3"])], resume_state=RailwayResumeConfig(cursor="c9"))

        assert _request_variables(result, 0)["after"] == "c9"

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self):
        result = _run("projects", [_projects_page(["p3"])])

        assert _request_variables(result, 0)["after"] is None

    def test_fan_out_resume_skips_completed_projects_and_uses_saved_cursor(self):
        result = _run(
            "services",
            [
                _projects_page(["p1", "p2", "p3"]),
                _connection(("project", "services"), [{"id": "s2b", "projectId": "p2"}]),
                _connection(("project", "services"), [{"id": "s3", "projectId": "p3"}]),
            ],
            resume_state=RailwayResumeConfig(cursor="c5", project_id="p2"),
        )

        first_child = _request_variables(result, 1)
        assert first_child["projectId"] == "p2"
        assert first_child["after"] == "c5"
        # p3 starts fresh — the saved cursor belongs to p2's connection only.
        assert _request_variables(result, 2)["after"] is None

    def test_fan_out_skips_project_deleted_mid_sync(self):
        result = _run(
            "services",
            [
                _projects_page(["p1", "p2"]),
                {"data": {"project": None}},
                _connection(("project", "services"), [{"id": "s2", "projectId": "p2"}]),
            ],
        )

        assert _batch_ids(result) == [["s2"]]

    def test_project_members_rows_carry_project_id(self):
        result = _run(
            "project_members",
            [
                _projects_page(["p1"]),
                {"data": {"projectMembers": [{"id": "u1", "email": "a@b.c", "role": "ADMIN"}]}},
            ],
        )

        assert result.items == [[{"project_id": "p1", "id": "u1", "email": "a@b.c", "role": "ADMIN"}]]

    def test_deployments_incremental_stops_once_page_predates_watermark(self):
        deployments_path = ("deployments",)
        result = _run(
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
            incremental_field="createdAt",
            db_incremental_field_last_value=datetime(2024, 6, 1, tzinfo=UTC),
        )

        # Both pages yielded (the boundary page merges/dedupes), but pagination stops there.
        assert result.raised is None
        assert _batch_ids(result) == [["d1", "d2"], ["d3", "d4"]]
        assert len(result.requests) == 3

    def test_not_authorized_error_matches_non_retryable_catalog(self):
        result = _run("projects", [{"errors": [{"message": "Not Authorized"}], "data": None}])

        assert result.raised is not None
        non_retryable = RailwaySource().get_non_retryable_errors()
        assert any(key in str(result.raised) for key in non_retryable)

    def test_problem_processing_request_error_is_retryable(self):
        # Railway returns this generic message as HTTP 200 + a GraphQL error for what their own
        # support forum confirms is usually a transient backend hiccup — it must retry like the
        # 429/5xx statuses below, not abort the sync on the first occurrence.
        with pytest.raises(RailwayRetryableError):
            railway._raise_for_graphql_errors({"errors": [{"message": "Problem processing request"}]})

    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_status_codes(self, status_code):
        result = SourceDriver(RailwaySource(), RailwaySourceConfig(api_token="token")).run(
            "projects", always(ScriptedResponse(status=status_code, json={}))
        )

        assert isinstance(result.raised, RailwayRetryableError)
        assert len(result.requests) > 1

    def test_source_response_shape_per_endpoint(self):
        deployments = _run("deployments", [_projects_page([])]).response
        assert deployments is not None
        assert deployments.primary_keys == ["id"]
        assert deployments.sort_mode == "desc"
        assert deployments.partition_mode == "datetime"
        assert deployments.partition_keys == ["createdAt"]

        members = _run("project_members", [_projects_page([])]).response
        assert members is not None
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
        with scripted_network([ScriptedResponse(json=payload)]) as network:
            is_valid, message = validate_credentials("token")

        assert network.requests_log[0].headers["authorization"] == "Bearer token"
        assert is_valid is expected_valid
        if expected_message_contains is None:
            assert message is None
        else:
            assert message is not None and expected_message_contains in message
