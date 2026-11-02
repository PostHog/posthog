from datetime import UTC, datetime
from typing import Any, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd import (
    BugherdResumeConfig,
    _format_bugherd_datetime,
    _incremental_window,
    _resource,
    bugherd_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.settings import BUGHERD_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.source import BugherdSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bugherd import (
    BugherdSourceConfig,
)


def _driver(api_key: str = "key") -> SourceDriver:
    return SourceDriver(BugherdSource(), BugherdSourceConfig(api_key=api_key))


def _page(name: str, rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={name: rows})


class TestFormatBugherdDatetime:
    def test_caps_future_datetime_to_now(self) -> None:
        far_future = datetime(2999, 1, 1, tzinfo=UTC)
        formatted = _format_bugherd_datetime(far_future)
        assert formatted != "2999-01-01T00:00:00Z"
        assert datetime.strptime(formatted, "%Y-%m-%dT%H:%M:%SZ") <= datetime.now(UTC).replace(tzinfo=None)

    def test_passes_through_already_formatted_string(self) -> None:
        # Our own `initial_value` seed round-trips through `convert` on the first sync.
        assert _format_bugherd_datetime("1970-01-01T00:00:00Z") == "1970-01-01T00:00:00Z"


class TestIncrementalWindow:
    @parameterized.expand(
        [
            ("updated_at", "updated_since"),
            ("created_at", "created_since"),
        ]
    )
    def test_shape(self, field_name: str, query_param: str) -> None:
        window = _incremental_window(field_name, query_param)

        assert window["cursor_path"] == field_name
        assert window["start_param"] == query_param
        assert window["initial_value"] == "1970-01-01T00:00:00Z"
        assert window["convert"] is _format_bugherd_datetime


class TestResource:
    def test_tasks_default_incremental_field_maps_to_updated_since(self) -> None:
        resource = _resource(BUGHERD_ENDPOINTS["Tasks"], should_use_incremental_field=True, incremental_field=None)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        endpoint = cast(dict[str, Any], resource["endpoint"])
        assert endpoint["incremental"]["start_param"] == "updated_since"


class TestValidateCredentials:
    def test_valid_key(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("valid-key") == (True, None)

        assert network.requests_log[0].path == "/api_v2/organization.json"
        assert network.requests_log[0].headers["authorization"] == "Basic dmFsaWQta2V5Ong="
        assert network.session_options[0]["redact_values"] == ("valid-key",)

    def test_invalid_key(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]) as network:
            assert validate_credentials("bad-key") == (False, "Invalid BugHerd API key.")

        assert network.requests_log[0].path == "/api_v2/organization.json"

    @parameterized.expand([(503,)])
    def test_other_status_is_reported(self, status_code: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))):
            result = validate_credentials("key")

        assert result == (False, f"BugHerd API returned an unexpected status ({status_code}).")


class TestBugherdSourceTopLevel:
    def test_flat_endpoint_seeds_paginator_from_saved_page(self) -> None:
        result = _driver().run("Users", [_page("users", [])], resume_state=BugherdResumeConfig(page=3))

        assert result.raised is None
        assert result.params("page") == ["3"]

    def test_flat_endpoint_does_not_load_state_when_cannot_resume(self) -> None:
        result = _driver().run("Users", [_page("users", [])])

        assert result.raised is None
        assert result.params("page") == ["1"]

    def test_flat_endpoint_saves_checkpoint_via_resume_hook(self) -> None:
        result = _driver().run("Users", [_page("users", [{"id": 1}]), _page("users", [])])

        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert BugherdResumeConfig(page=2) in result.saved_states

    def test_client_config_uses_http_basic_auth_with_x_password(self) -> None:
        result = _driver("secret-key").run("Projects", [_page("projects", [])])

        assert result.raised is None
        assert result.requests[0].headers["authorization"] == "Basic c2VjcmV0LWtleTp4"


class TestBugherdFanout:
    def test_tasks_incremental_passes_window_factory_mapped_to_created_since(self) -> None:
        result = _driver().run(
            "Tasks",
            route(
                {
                    "/api_v2/projects.json": [_page("projects", [{"id": 1000}]), _page("projects", [])],
                    "/api_v2/projects/1000/tasks.json": [
                        _page("tasks", [{"id": 1, "created_at": "2024-01-02T00:00:00Z"}]),
                        _page("tasks", []),
                    ],
                }
            ),
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="created_at",
        )

        assert result.raised is None
        assert result.rows[0]["id"] == 1
        assert result.params("created_since") == [None, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z", None]
        assert result.params("updated_since") == [None, None, None, None]

    def test_user_projects_fans_out_over_users_and_stays_full_refresh(self) -> None:
        result = _driver().run(
            "UserProjects",
            route(
                {
                    "/api_v2/users.json": [_page("users", [{"id": 4561}, {"id": 4562}]), _page("users", [])],
                    "/api_v2/users/4561/projects.json": [
                        _page("projects", [{"id": 1000, "name": "Site A"}, {"id": 1001, "name": "Site B"}]),
                        _page("projects", []),
                    ],
                    "/api_v2/users/4562/projects.json": [
                        _page("projects", [{"id": 1000, "name": "Site A"}]),
                        _page("projects", []),
                    ],
                }
            ),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="created_at",
        )

        # Project 1000 appears once per member, so the key must include the user.
        assert result.raised is None
        assert result.response is not None and result.response.primary_keys == ["user_id", "id"]
        assert sorted((row["user_id"], row["id"]) for row in result.rows) == [(4561, 1000), (4561, 1001), (4562, 1000)]
        assert result.params("created_since") == [None] * len(result.requests)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.build_dependent_resource")
    def test_tasks_fanout_seeds_resume_state_and_wires_hook(self, mock_build) -> None:
        mock_build.return_value = iter([])
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = BugherdResumeConfig(page=2)

        bugherd_source(api_key="key", endpoint="Tasks", team_id=1, job_id="job-1", resumable_source_manager=manager)

        _, kwargs = mock_build.call_args
        assert kwargs["initial_paginator_state"] == {"page": 2}

        kwargs["resume_hook"]({"page": 4})
        manager.save_state.assert_called_once_with(BugherdResumeConfig(page=4))


class TestBugherdChainedFanout:
    @parameterized.expand(
        [
            ("TaskComments", "comments", {"id": 8801, "text": "reproduced"}),
            ("TaskAttachments", "attachments", {"id": 331, "file_name": "screenshot.png"}),
        ]
    )
    def test_walks_projects_then_tasks_then_child(self, endpoint: str, resource: str, row: dict[str, Any]) -> None:
        child_path = f"/api_v2/projects/1000/tasks/98765/{resource}.json"
        result = _driver().run(
            endpoint,
            route(
                {
                    "/api_v2/projects.json": [_page("projects", [{"id": 1000}]), _page("projects", [])],
                    "/api_v2/projects/1000/tasks.json": [
                        _page("tasks", [{"id": 98765, "project_id": 1000}]),
                        _page("tasks", []),
                    ],
                    child_path: [_page(resource, [row]), _page(resource, [])],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{**row, "task_id": 98765, "project_id": 1000}]
        assert result.response is not None and result.response.primary_keys == ["task_id", "id"]
        assert child_path in result.paths

    def test_skips_a_task_that_disappeared_between_pages(self) -> None:
        result = _driver().run(
            "TaskComments",
            route(
                {
                    "/api_v2/projects.json": [_page("projects", [{"id": 1000}]), _page("projects", [])],
                    "/api_v2/projects/1000/tasks.json": [
                        _page("tasks", [{"id": 1, "project_id": 1000}, {"id": 2, "project_id": 1000}]),
                        _page("tasks", []),
                    ],
                    "/api_v2/projects/1000/tasks/1/comments.json": [ScriptedResponse(status=404, json={})],
                    "/api_v2/projects/1000/tasks/2/comments.json": [
                        _page("comments", [{"id": 9, "text": "still here"}]),
                        _page("comments", []),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [9]
        assert "/api_v2/projects/1000/tasks/1/comments.json" in result.paths


class TestBugherdProjectFanoutEndpoints:
    @parameterized.expand(
        [
            ("ArchivedTasks", "/api_v2/projects/{project_id}/tasks/archive.json"),
            ("FeedbackTasks", "/api_v2/projects/{project_id}/tasks/feedback.json"),
        ]
    )
    def test_task_list_stays_full_refresh_when_incremental_is_requested(self, endpoint: str, path: str) -> None:
        # These endpoints take no `updated_since`/`created_since`, so they declare no
        # incremental fields and no query-param mapping — asking for incremental anyway
        # must not reach the window factory, which would KeyError.
        child_path = path.format(project_id=1000)
        result = _driver().run(
            endpoint,
            route(
                {
                    "/api_v2/projects.json": [_page("projects", [{"id": 1000}]), _page("projects", [])],
                    child_path: [_page("tasks", [{"id": 1}]), _page("tasks", [])],
                }
            ),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="updated_at",
        )

        assert result.raised is None
        assert result.response is not None and result.response.primary_keys == ["id"]
        assert child_path in result.paths
        assert result.params("updated_since") == [None] * len(result.requests)
        assert result.params("created_since") == [None] * len(result.requests)

    def test_columns_child_is_not_paginated(self) -> None:
        result = _driver().run(
            "Columns",
            route(
                {
                    "/api_v2/projects.json": [_page("projects", [{"id": 1000}]), _page("projects", [])],
                    "/api_v2/projects/1000/columns.json": [_page("columns", [{"id": 7}])],
                }
            ),
        )

        # Columns returns its whole collection in one response; a page paginator would
        # re-request page 2 forever on an API that ignores `page`.
        assert result.raised is None
        assert result.response is not None and result.response.primary_keys == ["project_id", "id"]
        assert result.paths.count("/api_v2/projects/1000/columns.json") == 1
        assert result.params("page") == ["1", None, "2"]
