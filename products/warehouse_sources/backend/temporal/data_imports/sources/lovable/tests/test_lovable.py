import json
from typing import Any

from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.lovable.lovable import (
    LovableResumeConfig,
    _ParentRef,
    check_endpoint_permissions,
    lovable_source,
    resume_position,
    validate_credentials,
)

CLIENT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client."
    "make_tracked_session"
)
PROBE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.lovable.lovable.make_tracked_session"
)


def _page(rows: list[dict[str, Any]], next_cursor: str | None = None, status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(
        {"data": rows, "pagination": {"has_more": next_cursor is not None, "next_cursor": next_cursor}}
    ).encode()
    return response


def _error(status_code: int, error_type: str = "payment_required") -> Response:
    response = Response()
    response.status_code = status_code
    response.url = "https://api.lovable.dev/v1/workspaces"
    response._content = json.dumps(
        {"status": status_code, "type": error_type, "title": "Nope", "request_id": "req-1"}
    ).encode()
    return response


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[str]:
    """Point a mocked session at `responses` and record the URL of every request it sends."""
    real_session = requests.Session()
    urls: list[str] = []
    session.headers = {}

    def _prepare(request: Any) -> Any:
        prepared = real_session.prepare_request(request)
        urls.append(prepared.url or "")
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return urls


def _manager(resume_state: LovableResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(endpoint: str, manager: mock.MagicMock | None = None) -> Any:
    return lovable_source(
        api_key="lov_key",
        api_version="v1",
        endpoint=endpoint,
        resumable_source_manager=manager or _manager(),
    )


class TestLovableSourceTransport:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_account_endpoint_follows_the_cursor(self, mock_session: mock.MagicMock) -> None:
        urls = _wire(
            mock_session.return_value,
            [_page([{"id": "ws-1"}], next_cursor="c1"), _page([{"id": "ws-2"}])],
        )

        rows = _rows(_run("Workspaces"))

        assert [row["id"] for row in rows] == ["ws-1", "ws-2"]
        assert urls[0] == "https://api.lovable.dev/v1/workspaces?limit=100"
        assert "cursor=c1" in urls[1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_workspace_endpoint_binds_the_workspace_into_the_path_and_the_row(
        self, mock_session: mock.MagicMock
    ) -> None:
        urls = _wire(
            mock_session.return_value,
            [
                _page([{"id": "ws-1"}, {"id": "ws-2"}]),
                _page([{"user_id": "u-1", "workspace_id": "ws-1"}]),
                _page([{"user_id": "u-2", "workspace_id": "ws-2"}]),
            ],
        )

        rows = _rows(_run("WorkspaceMembers"))

        assert [(row["workspace_id"], row["user_id"]) for row in rows] == [("ws-1", "u-1"), ("ws-2", "u-2")]
        assert urls[1].startswith("https://api.lovable.dev/v1/workspaces/ws-1/members?")
        assert urls[2].startswith("https://api.lovable.dev/v1/workspaces/ws-2/members?")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_members_request_asks_for_pending_invites_and_the_endpoint_page_size(
        self, mock_session: mock.MagicMock
    ) -> None:
        urls = _wire(mock_session.return_value, [_page([{"id": "ws-1"}]), _page([{"user_id": "u-1"}])])

        _rows(_run("WorkspaceMembers"))

        assert "status=all" in urls[1]
        assert "limit=50" in urls[1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_projects_pass_the_workspace_as_a_query_param_with_unnarrowed_filters(
        self, mock_session: mock.MagicMock
    ) -> None:
        urls = _wire(mock_session.return_value, [_page([{"id": "ws-1"}]), _page([{"id": "p-1"}])])

        rows = _rows(_run("Projects"))

        assert [row["id"] for row in rows] == ["p-1"]
        assert urls[1].startswith("https://api.lovable.dev/v1/projects?")
        assert "workspace_id=ws-1" in urls[1]
        assert "visibility=all" in urls[1]
        assert "publish_status=any" in urls[1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_project_endpoint_fans_out_through_workspaces_and_stamps_both_parents(
        self, mock_session: mock.MagicMock
    ) -> None:
        urls = _wire(
            mock_session.return_value,
            [
                _page([{"id": "ws-1"}]),
                _page([{"id": "p-1"}, {"id": "p-2"}]),
                _page([{"user_id": "u-1"}]),
                _page([{"user_id": "u-2"}]),
            ],
        )

        rows = _rows(_run("ProjectCollaborators"))

        assert [(row["workspace_id"], row["project_id"], row["user_id"]) for row in rows] == [
            ("ws-1", "p-1", "u-1"),
            ("ws-1", "p-2", "u-2"),
        ]
        assert urls[2].startswith("https://api.lovable.dev/v1/projects/p-1/collaborators?")
        assert urls[3].startswith("https://api.lovable.dev/v1/projects/p-2/collaborators?")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_parents_without_an_id_are_skipped(self, mock_session: mock.MagicMock) -> None:
        _wire(
            mock_session.return_value,
            [_page([{"name": "no id here"}, {"id": "ws-2"}]), _page([{"user_id": "u-1"}])],
        )

        rows = _rows(_run("WorkspaceMembers"))

        assert [row["workspace_id"] for row in rows] == ["ws-2"]

    @parameterized.expand(
        [
            ("Workspaces", ["id"], "created_at"),
            ("Projects", ["id"], "created_at"),
            ("WorkspaceMembers", ["workspace_id", "user_id"], "invited_at"),
            ("WorkspaceCreditHistory", ["workspace_id", "id"], "occurred_at"),
            ("ProjectCollaborators", ["project_id", "user_id"], None),
            ("ProjectSecurityScans", ["project_id", "scan_id"], "started_at"),
            ("ProjectPiiLabels", ["project_id", "id"], "found_at"),
        ]
    )
    def test_primary_keys_and_partitioning_per_endpoint(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        response = _run(endpoint)

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.partition_mode == ("datetime" if partition_key else None)


class TestLovableResume:
    @parameterized.expand(
        [
            ("no_saved_state", None, 0, None),
            ("cursor_resumes_that_parent", LovableResumeConfig(workspace_id="ws-2", cursor="c9"), 1, "c9"),
            ("finished_parent_moves_on", LovableResumeConfig(workspace_id="ws-2"), 2, None),
            ("unknown_parent_restarts", LovableResumeConfig(workspace_id="gone", cursor="c9"), 0, None),
        ]
    )
    def test_resume_position(
        self, _name: str, resume: LovableResumeConfig | None, expected_index: int, expected_cursor: str | None
    ) -> None:
        parents = [_ParentRef(workspace_id="ws-1"), _ParentRef(workspace_id="ws-2"), _ParentRef(workspace_id="ws-3")]

        assert resume_position(parents, resume) == (expected_index, expected_cursor)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoint_records_the_parent_and_next_cursor_then_marks_it_finished(
        self, mock_session: mock.MagicMock
    ) -> None:
        _wire(
            mock_session.return_value,
            [
                _page([{"id": "ws-1"}]),
                _page([{"user_id": "u-1"}], next_cursor="c1"),
                _page([{"user_id": "u-2"}]),
            ],
        )
        manager = _manager()

        _rows(_run("WorkspaceMembers", manager))

        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            LovableResumeConfig(workspace_id="ws-1", cursor="c1"),
            LovableResumeConfig(workspace_id="ws-1", cursor=None),
        ]
        manager.clear_state.assert_called_once()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumed_run_seeds_the_cursor_and_skips_earlier_parents(self, mock_session: mock.MagicMock) -> None:
        urls = _wire(
            mock_session.return_value,
            [_page([{"id": "ws-1"}, {"id": "ws-2"}]), _page([{"user_id": "u-2"}])],
        )

        rows = _rows(_run("WorkspaceMembers", _manager(LovableResumeConfig(workspace_id="ws-2", cursor="c9"))))

        assert [row["user_id"] for row in rows] == ["u-2"]
        assert urls[1].startswith("https://api.lovable.dev/v1/workspaces/ws-2/members?")
        assert "cursor=c9" in urls[1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_finished_parent_checkpoint_yields_nothing_more(self, mock_session: mock.MagicMock) -> None:
        _wire(mock_session.return_value, [_page([{"id": "ws-1"}])])

        rows = _rows(_run("WorkspaceMembers", _manager(LovableResumeConfig(workspace_id="ws-1"))))

        assert rows == []


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True, None),
            ("bad_key", 401, False, "Invalid Lovable API key. Create a new key in Lovable and reconnect."),
            ("server_error", 500, False, "Could not connect to Lovable. Check the API key and try again."),
        ]
    )
    @mock.patch(PROBE_SESSION_PATCH)
    def test_status_maps_to_message(
        self,
        _name: str,
        status_code: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: mock.MagicMock,
    ) -> None:
        response = Response()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("lov_key", "v1") == (expected_valid, expected_message)
        assert mock_session.return_value.get.call_args.args[0] == "https://api.lovable.dev/v1/me"

    @mock.patch(PROBE_SESSION_PATCH)
    def test_transport_failure_is_not_valid(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("nope")

        is_valid, message = validate_credentials("lov_key", "v1")

        assert is_valid is False
        assert message == "Could not connect to Lovable. Check the API key and try again."


class TestCheckEndpointPermissions:
    @parameterized.expand(
        [
            ("plan_gated", _error(402), "This table needs Lovable's Enterprise plan or higher."),
            (
                "forbidden",
                _error(403, "forbidden"),
                "This Lovable API key does not have permission to read this table.",
            ),
            ("readable", _page([{"user_id": "u-1"}]), None),
            # An unexpected status is not a denial, so the table must not be disabled over it.
            ("unexpected_status", _error(404, "not_found"), None),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_probe_status_maps_to_a_reason(
        self, _name: str, probe_response: Response, expected_reason: str | None, mock_session: mock.MagicMock
    ) -> None:
        _wire(mock_session.return_value, [_page([{"id": "ws-1"}]), probe_response])

        assert check_endpoint_permissions("lov_key", "v1", ["WorkspaceMembers"]) == {
            "WorkspaceMembers": expected_reason
        }

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_account_with_no_workspaces_reports_no_reason(self, mock_session: mock.MagicMock) -> None:
        _wire(mock_session.return_value, [_page([])])

        assert check_endpoint_permissions("lov_key", "v1", ["WorkspaceMembers"]) == {"WorkspaceMembers": None}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_endpoint_missing_from_the_catalog_reports_no_reason(self, mock_session: mock.MagicMock) -> None:
        _wire(mock_session.return_value, [_page([{"id": "ws-1"}])])

        assert check_endpoint_permissions("lov_key", "v1", ["RetiredTable"]) == {"RetiredTable": None}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_project_scoped_table_probes_a_project(self, mock_session: mock.MagicMock) -> None:
        urls = _wire(
            mock_session.return_value,
            [_page([{"id": "ws-1"}]), _page([{"id": "p-1"}]), _error(402)],
        )

        permissions = check_endpoint_permissions("lov_key", "v1", ["ProjectSecurityScans"])

        assert permissions == {"ProjectSecurityScans": "This table needs Lovable's Business plan or higher."}
        assert urls[2].startswith("https://api.lovable.dev/v1/projects/p-1/security-scans?")
