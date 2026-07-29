import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.semgrep import (
    SEMGREP_BASE_URL,
    SemgrepResumeConfig,
    semgrep_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.settings import (
    ENDPOINTS,
    SEMGREP_ENDPOINTS,
)

# RESTClient uses the session the semgrep client config hands it, built here via make_tracked_session.
SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.semgrep.make_tracked_session"

DEPLOYMENT = {"id": 123, "slug": "my-org", "name": "My Org"}
OTHER_DEPLOYMENT = {"id": 456, "slug": "other-org", "name": "Other Org"}


def _json_response(body: Any, status: int = 200) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp.url = f"{SEMGREP_BASE_URL}/deployments"
    resp.reason = "OK" if status < 400 else "Error"
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: SemgrepResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    manager.saved = []
    manager.save_state.side_effect = lambda state: manager.saved.append(state)
    return manager


def _wire(session: mock.MagicMock, responses: list[requests.Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy per prepare.
    """
    session.headers = {}
    log: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        log.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock(url=request.url, is_redirect=False)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return log


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _child_requests(log: list[dict[str, Any]], marker: str) -> list[dict[str, Any]]:
    return [entry for entry in log if marker in entry["url"]]


class TestSingleEndpoint:
    @mock.patch(SESSION_PATCH)
    def test_deployments_is_a_single_unpaginated_request(self, MockSession: Any) -> None:
        session = MockSession.return_value
        log = _wire(session, [_json_response({"deployments": [DEPLOYMENT]})])

        manager = _make_manager()
        rows = _rows(semgrep_source("token", "deployments", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [DEPLOYMENT]
        assert len(log) == 1
        assert log[0]["url"] == f"{SEMGREP_BASE_URL}/deployments"
        assert manager.saved == []

    @mock.patch(SESSION_PATCH)
    def test_non_object_payload_raises_value_error(self, MockSession: Any) -> None:
        # A non-object 200 is a permanent contract violation: data_selector_required fails loud
        # instead of silently syncing 0 rows, and it must not be retried.
        session = MockSession.return_value
        _wire(session, [_json_response([{"id": 1}])])

        with pytest.raises(ValueError):
            _rows(
                semgrep_source("token", "deployments", team_id=1, job_id="j", resumable_source_manager=_make_manager())
            )
        assert session.send.call_count == 1

    @mock.patch(SESSION_PATCH)
    def test_client_error_raises_http_error(self, MockSession: Any) -> None:
        # A 401/403 surfaces as an HTTPError so get_non_retryable_errors can match and stop the sync.
        session = MockSession.return_value
        _wire(session, [_json_response({}, status=401)])

        with pytest.raises(requests.HTTPError):
            _rows(
                semgrep_source("token", "deployments", team_id=1, job_id="j", resumable_source_manager=_make_manager())
            )
        assert session.send.call_count == 1


class TestPageNumberFanout:
    @mock.patch(SESSION_PATCH)
    def test_paginates_until_short_page_and_injects_deployment(self, MockSession: Any) -> None:
        session = MockSession.return_value
        page_size = SEMGREP_ENDPOINTS["sast_findings"].page_size
        assert page_size is not None
        full_page = [{"id": i} for i in range(page_size)]
        log = _wire(
            session,
            [
                _json_response({"deployments": [DEPLOYMENT]}),
                _json_response({"findings": full_page}),
                _json_response({"findings": [{"id": page_size}]}),
            ],
        )

        manager = _make_manager()
        rows = _rows(semgrep_source("token", "sast_findings", team_id=1, job_id="j", resumable_source_manager=manager))

        assert len(rows) == page_size + 1
        # Every row carries the parent deployment, keeping the composite primary key unique.
        assert all(row["deployment_id"] == 123 and row["deployment_slug"] == "my-org" for row in rows)
        # sast_findings requests pin issue_type and dedup so counts match the Semgrep UI.
        findings = _child_requests(log, "/findings")
        assert all(req["params"]["issue_type"] == "sast" and req["params"]["dedup"] == "true" for req in findings)
        assert [req["params"]["page"] for req in findings] == [0, 1]
        # Checkpoint saved after the full page points at the next page (page 1); short page ends it.
        assert any((state.fanout_state or {}).get("child_state") == {"page": 1} for state in manager.saved)

    @mock.patch(SESSION_PATCH)
    def test_sca_findings_requests_sca_issue_type(self, MockSession: Any) -> None:
        session = MockSession.return_value
        log = _wire(
            session,
            [_json_response({"deployments": [DEPLOYMENT]}), _json_response({"findings": [{"id": 1}]})],
        )

        _rows(semgrep_source("token", "sca_findings", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert any(req["params"].get("issue_type") == "sca" for req in _child_requests(log, "/findings"))

    @mock.patch(SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response({"deployments": [DEPLOYMENT]}), _json_response({"projects": []})])

        rows = _rows(
            semgrep_source("token", "projects", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )
        assert rows == []

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession: Any) -> None:
        session = MockSession.return_value
        log = _wire(
            session,
            [_json_response({"deployments": [DEPLOYMENT]}), _json_response({"projects": [{"id": 7}]})],
        )

        # Resume mid-way through my-org at page 2; pages 0-1 must not be re-fetched.
        manager = _make_manager(
            SemgrepResumeConfig(
                fanout_state={"completed": [], "current": "/deployments/my-org/projects", "child_state": {"page": 2}}
            )
        )
        rows = _rows(semgrep_source("token", "projects", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [row["id"] for row in rows] == [7]
        project_reqs = _child_requests(log, "/projects")
        assert len(project_reqs) == 1
        assert project_reqs[0]["params"]["page"] == 2

    @mock.patch(SESSION_PATCH)
    def test_vanished_bookmarked_deployment_starts_over(self, MockSession: Any) -> None:
        session = MockSession.return_value
        log = _wire(
            session,
            [_json_response({"deployments": [DEPLOYMENT]}), _json_response({"projects": [{"id": 1}]})],
        )

        # The bookmarked deployment path no longer matches any current deployment, so the present
        # one starts fresh from page 0 (merge dedupes any re-pulled rows).
        manager = _make_manager(
            SemgrepResumeConfig(
                fanout_state={"completed": [], "current": "/deployments/gone/projects", "child_state": {"page": 5}}
            )
        )
        rows = _rows(semgrep_source("token", "projects", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [row["id"] for row in rows] == [1]
        assert _child_requests(log, "/projects")[0]["params"]["page"] == 0

    @mock.patch(SESSION_PATCH)
    def test_fans_out_over_every_deployment_and_bookmarks_completed(self, MockSession: Any) -> None:
        session = MockSession.return_value
        log = _wire(
            session,
            [
                _json_response({"deployments": [DEPLOYMENT, OTHER_DEPLOYMENT]}),
                _json_response({"projects": [{"id": 1}]}),
                _json_response({"projects": [{"id": 2}]}),
            ],
        )

        manager = _make_manager()
        rows = _rows(semgrep_source("token", "projects", team_id=1, job_id="j", resumable_source_manager=manager))

        assert {(row["id"], row["deployment_slug"]) for row in rows} == {(1, "my-org"), (2, "other-org")}
        # A crash after the first deployment must not re-run it: its child path is checkpointed done.
        assert any(
            "/deployments/my-org/projects" in (state.fanout_state or {}).get("completed", []) for state in manager.saved
        )
        assert len(_child_requests(log, "/projects")) == 2


class TestCursorFanout:
    @mock.patch(SESSION_PATCH)
    def test_follows_cursor_until_absent(self, MockSession: Any) -> None:
        session = MockSession.return_value
        log = _wire(
            session,
            [
                _json_response({"deployments": [DEPLOYMENT]}),
                _json_response({"findings": [{"id": "1"}], "cursor": "abc"}),
                _json_response({"findings": [{"id": "2"}]}),
            ],
        )

        manager = _make_manager()
        rows = _rows(semgrep_source("token", "secrets", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [row["id"] for row in rows] == ["1", "2"]
        # secrets fans out on the deployment id, not slug.
        secrets = _child_requests(log, "/secrets")
        assert all("/deployments/123/secrets" in req["url"] for req in secrets)
        assert "cursor" not in secrets[0]["params"]
        assert secrets[1]["params"]["cursor"] == "abc"
        assert any((state.fanout_state or {}).get("child_state") == {"cursor": "abc"} for state in manager.saved)

    @mock.patch(SESSION_PATCH)
    def test_terminates_on_repeated_cursor(self, MockSession: Any) -> None:
        # A server echoing its final cursor must not loop forever.
        session = MockSession.return_value
        log = _wire(
            session,
            [
                _json_response({"deployments": [DEPLOYMENT]}),
                _json_response({"findings": [{"id": "1"}], "cursor": "abc"}),
                _json_response({"findings": [{"id": "2"}], "cursor": "abc"}),
            ],
        )

        rows = _rows(
            semgrep_source("token", "secrets", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )
        assert [row["id"] for row in rows] == ["1", "2"]
        assert len(_child_requests(log, "/secrets")) == 2

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession: Any) -> None:
        session = MockSession.return_value
        log = _wire(
            session,
            [_json_response({"deployments": [DEPLOYMENT]}), _json_response({"findings": [{"id": "2"}]})],
        )

        manager = _make_manager(
            SemgrepResumeConfig(
                fanout_state={
                    "completed": [],
                    "current": "/deployments/123/secrets",
                    "child_state": {"cursor": "abc"},
                }
            )
        )
        rows = _rows(semgrep_source("token", "secrets", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [row["id"] for row in rows] == ["2"]
        secrets = _child_requests(log, "/secrets")
        assert len(secrets) == 1
        assert secrets[0]["params"]["cursor"] == "abc"


class TestSemgrepSourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, name: str) -> None:
        config = SEMGREP_ENDPOINTS[name]
        with mock.patch(SESSION_PATCH):
            response = semgrep_source("token", name, team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.name == name
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
        else:
            assert response.partition_keys is None

    def test_fan_out_endpoints_key_on_deployment_and_id(self) -> None:
        # Guards against dropping the parent id from a fan-out child's key, which would seed
        # duplicate rows if a token ever spans multiple deployments.
        for name, config in SEMGREP_ENDPOINTS.items():
            if name == "deployments":
                assert config.primary_keys == ["id"]
            else:
                assert config.primary_keys == ["deployment_id", "id"]

    def test_partition_keys_are_stable_creation_timestamps(self) -> None:
        # Partitioning on a churning field (updated_at) rewrites partitions on every sync.
        partitioned = {name: cfg.partition_key for name, cfg in SEMGREP_ENDPOINTS.items() if cfg.partition_key}
        assert partitioned == {"sast_findings": "created_at", "sca_findings": "created_at", "secrets": "createdAt"}


class TestValidateCredentials:
    @mock.patch(SESSION_PATCH)
    def test_ok(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("token") is True

    @mock.patch(SESSION_PATCH)
    def test_unauthorized(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("token") is False

    @mock.patch(SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session: Any) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False
