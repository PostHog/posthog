import json
from typing import Any, Optional

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.hex import hex as hex_module
from products.warehouse_sources.backend.temporal.data_imports.sources.hex.hex import (
    HexResumeConfig,
    hex_source,
    normalize_workspace_host,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(body: dict[str, Any], *, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _projects_page(ids: list[str], after: Optional[str] = None) -> Response:
    return _response(
        {
            "values": [{"id": project_id, "createdAt": "2026-01-01T00:00:00.000Z"} for project_id in ids],
            "pagination": {"after": after, "before": None},
        }
    )


def _runs_page(runs: list[dict[str, Any]]) -> Response:
    return _response({"runs": runs, "nextPage": None, "previousPage": None, "traceId": "t"})


def _make_manager(resume_state: Optional[HexResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when
    each request is prepared rather than inspecting the shared dict after the run.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str = "projects", manager: Optional[mock.MagicMock] = None, workspace_url: Optional[str] = None):
    return hex_source(
        api_key="tok",
        workspace_url=workspace_url,
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
    )


class TestNormalizeWorkspaceHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "app.hex.tech"),
            ("", "app.hex.tech"),
            ("   ", "app.hex.tech"),
            ("acme.hex.tech", "acme.hex.tech"),
            ("https://acme.hex.tech", "acme.hex.tech"),
            ("http://acme.hex.tech/", "acme.hex.tech"),
            ("acme.hex.tech/api/v1", "acme.hex.tech"),
            ("  https://app.hex.tech  ", "app.hex.tech"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_workspace_host(raw) == expected


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(hex_module, "make_tracked_session", return_value=session)

    def _resp(self, *, status_code=200, text=""):
        response = mock.MagicMock()
        response.status_code = status_code
        response.is_redirect = status_code in (301, 302, 303, 307, 308)
        response.is_permanent_redirect = status_code in (301, 308)
        response.text = text
        response.json.side_effect = Exception("not json")
        return response

    def test_success_hits_default_host(self):
        with self._patch_session(self._resp(status_code=200)) as patched:
            assert validate_credentials(None, "tok") == (True, None)
            url = patched.return_value.get.call_args.args[0]
            assert url == "https://app.hex.tech/api/v1/projects"

    def test_custom_workspace_url_is_used(self):
        with self._patch_session(self._resp(status_code=200)) as patched:
            assert validate_credentials("https://acme.hex.tech", "tok") == (True, None)
            url = patched.return_value.get.call_args.args[0]
            assert url == "https://acme.hex.tech/api/v1/projects"

    def test_invalid_token(self):
        with self._patch_session(self._resp(status_code=401)):
            assert validate_credentials(None, "tok") == (False, "Invalid Hex API token")

    def test_403_at_source_create_is_accepted(self):
        with self._patch_session(self._resp(status_code=403)):
            assert validate_credentials(None, "tok", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with self._patch_session(self._resp(status_code=403)):
            valid, msg = validate_credentials(None, "tok", schema_name="projects")
            assert valid is False
            assert msg is not None

    def test_invalid_host_short_circuits(self):
        valid, msg = validate_credentials("not a host!", "tok")
        assert valid is False
        assert msg == "Invalid Hex workspace URL"

    def test_request_exception_returns_failure(self):
        import requests

        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials(None, "tok")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        # A workspace host that 3xx-redirects (potentially to an internal address) must be
        # rejected, not followed (SSRF).
        with self._patch_session(self._resp(status_code=302)) as patched:
            valid, msg = validate_credentials("acme.hex.tech", "tok")
            assert valid is False
            assert msg == hex_module.HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        # When a team_id is supplied, a host that resolves to an internal address is rejected
        # before any HTTP request is made (SSRF guard).
        with (
            mock.patch.object(hex_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(self._resp(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()


class TestHexSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, sort_mode",
        [
            ("projects", ["id"], "asc"),
            ("project_runs", ["projectId", "runId"], "desc"),
            ("users", ["id"], "asc"),
            ("groups", ["id"], "asc"),
            ("collections", ["id"], "asc"),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, sort_mode):
        response = _source(endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode

    def test_projects_partitioned_on_created_at(self):
        response = _source(endpoint="projects")
        assert response.partition_keys == ["createdAt"]
        assert response.partition_mode == "datetime"

    def test_project_runs_not_partitioned(self):
        # startTime is null for pending runs, so runs can't be datetime-partitioned.
        response = _source(endpoint="project_runs")
        assert response.partition_keys is None
        assert response.partition_mode is None


class TestHexCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_after_cursor_across_pages(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_projects_page(["p1", "p2"], after="cur-1"), _projects_page(["p3"], after=None)])
        rows = _rows(_source())

        assert [r["id"] for r in rows] == ["p1", "p2", "p3"]
        assert snaps[0]["url"] == "https://app.hex.tech/api/v1/projects"
        assert snaps[0]["params"]["limit"] == 100
        assert snaps[0]["params"]["sortBy"] == "CREATED_AT"
        assert snaps[0]["params"]["sortDirection"] == "ASC"
        assert "after" not in snaps[0]["params"]
        assert snaps[1]["params"]["after"] == "cur-1"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_terminates_even_with_cursor(self, MockSession):
        # An `after` token on an empty page must end pagination rather than loop forever.
        session = MockSession.return_value
        _wire(session, [_projects_page([], after="cur-1")])
        rows = _rows(_source())

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_projects_page(["p1"], after="cur-1"), _projects_page(["p2"], after=None)])
        manager = _make_manager()
        _rows(_source(manager=manager))

        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, HexResumeConfig)
        assert saved.paginator_state == {"cursor": "cur-1"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_projects_page(["p9"], after=None)])
        manager = _make_manager(HexResumeConfig(paginator_state={"cursor": "resume-cur"}))
        rows = _rows(_source(manager=manager))

        assert snaps[0]["params"]["after"] == "resume-cur"
        assert [r["id"] for r in rows] == ["p9"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_custom_workspace_url_reaches_requests(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_projects_page(["p1"], after=None)])
        _rows(_source(workspace_url="https://acme.hex.tech"))

        assert snaps[0]["url"] == "https://acme.hex.tech/api/v1/projects"


class TestProjectRunsFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_per_project_with_offset_pagination(self, MockSession):
        session = MockSession.return_value
        full_page = [{"runId": f"r{i}", "projectId": "p1", "status": "COMPLETED"} for i in range(100)]
        snaps = _wire(
            session,
            [
                _projects_page(["p1", "p2"], after=None),
                _runs_page(full_page),
                _runs_page([{"runId": "r100", "projectId": "p1", "status": "ERRORED"}]),
                _runs_page([{"runId": "r-b", "projectId": "p2", "status": "COMPLETED"}]),
            ],
        )
        rows = _rows(_source(endpoint="project_runs"))

        assert len(rows) == 102
        assert {r["projectId"] for r in rows} == {"p1", "p2"}
        assert snaps[0]["url"] == "https://app.hex.tech/api/v1/projects"
        assert snaps[1]["url"] == "https://app.hex.tech/api/v1/projects/p1/runs"
        assert snaps[1]["params"] == {"offset": 0, "limit": 100}
        # A full page advances the offset; a short page ends that project's pagination.
        assert snaps[2]["params"]["offset"] == 100
        assert snaps[3]["url"] == "https://app.hex.tech/api/v1/projects/p2/runs"
        assert snaps[3]["params"]["offset"] == 0

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_projects(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _projects_page(["p1", "p2"], after=None),
                _runs_page([{"runId": "r-b", "projectId": "p2", "status": "COMPLETED"}]),
            ],
        )
        manager = _make_manager(
            HexResumeConfig(
                paginator_state={"completed": ["/v1/projects/p1/runs"], "current": None, "child_state": None}
            )
        )
        rows = _rows(_source(endpoint="project_runs", manager=manager))

        assert [r["runId"] for r in rows] == ["r-b"]
        run_urls = [s["url"] for s in snaps[1:]]
        assert run_urls == ["https://app.hex.tech/api/v1/projects/p2/runs"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_completed_projects(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _projects_page(["p1"], after=None),
                _runs_page([{"runId": "r1", "projectId": "p1", "status": "COMPLETED"}]),
            ],
        )
        manager = _make_manager()
        _rows(_source(endpoint="project_runs", manager=manager))

        final_state = manager.save_state.call_args.args[0]
        assert isinstance(final_state, HexResumeConfig)
        assert final_state.paginator_state["completed"] == ["/v1/projects/p1/runs"]
        assert final_state.paginator_state["current"] is None


class TestRuntimeHostCheck:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_blocks_unsafe_workspace_host_before_any_request(self, MockSession):
        # The configured host is re-checked at run time (DNS rebinding) before any request.
        session = MockSession.return_value
        _wire(session, [_projects_page(["p1"], after=None)])
        with mock.patch.object(hex_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(hex_module.HexHostNotAllowedError):
                _rows(_source())
        session.send.assert_not_called()
