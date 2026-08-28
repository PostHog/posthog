import json
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.settings import (
    INCREMENTAL_FIELDS,
    TODOIST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.todoist import (
    PAGE_LIMIT,
    TodoistResumeConfig,
    todoist_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the todoist module.
TODOIST_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.todoist.todoist.make_tracked_session"
)
# Kill tenacity's backoff so retry classification tests don't actually sleep.
SLEEP_PATCH = "tenacity.nap.time.sleep"

BASE = "https://api.todoist.com/api/v1"


def _resp(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _norm(url: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    parts = urlsplit(url)
    return parts.path, tuple(sorted(parse_qsl(parts.query)))


def _make_manager(resume_state: TodoistResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses_by_url: dict[str, list[Response]]) -> list[dict[str, Any]]:
    """Wire a mock session that resolves each request by its fully-encoded URL.

    Values are per-URL queues so a URL can return different responses across retries/pages. Returns a
    list capturing each request's params snapshot at prepare time (the params dict is mutated in place
    across pages, so a post-run read would show only the final state).
    """
    session.headers = {}
    normalized: dict[tuple[str, tuple[tuple[str, str], ...]], list[Response]] = {
        _norm(url): list(queue) for url, queue in responses_by_url.items()
    }
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> Any:
        param_snapshots.append(dict(request.params or {}))
        return request.prepare()

    def _send(prepared: Any, **_kwargs: Any) -> Response:
        queue = normalized.get(_norm(prepared.url))
        if not queue:
            raise AssertionError(f"unexpected request url {prepared.url!r}")
        return queue.pop(0)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return param_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(endpoint: str, responses_by_url: dict[str, list[Response]], manager: mock.MagicMock) -> Any:
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        params = _wire(session, responses_by_url)
        rows = _rows(
            todoist_source(
                api_token="tok",
                endpoint=endpoint,
                team_id=1,
                job_id="job",
                resumable_source_manager=manager,
            )
        )
    return rows, params


class TestSourceResponseShape:
    @parameterized.expand(
        [
            ("tasks", ["id"], "datetime", "added_at"),
            ("projects", ["id"], "datetime", "created_at"),
            ("sections", ["id"], None, None),
            ("labels", ["id"], None, None),
            ("collaborators", ["project_id", "id"], None, None),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(
        self,
        endpoint: str,
        expected_keys: list[str],
        expected_partition_mode: str | None,
        expected_partition_key: str | None,
        MockSession: Any,
    ) -> None:
        response = todoist_source(
            api_token="tok",
            endpoint=endpoint,
            team_id=1,
            job_id="job",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.partition_mode == expected_partition_mode
        assert response.partition_keys == ([expected_partition_key] if expected_partition_key else None)
        # Ascending order is the safe default; we never declare desc here.
        assert response.sort_mode == "asc"


class TestEndpointConfig:
    def test_collaborators_is_fan_out_with_composite_key(self) -> None:
        config = TODOIST_ENDPOINTS["collaborators"]
        assert config.fan_out_over_projects is True
        # A collaborator can belong to many projects, so the key must include the parent project.
        assert config.primary_keys == ["project_id", "id"]
        assert config.partition_key is None
        # Fan-out adds an API request per project, so it's opt-in.
        assert config.should_sync_default is False

    @parameterized.expand(
        [
            ("tasks", "added_at"),
            ("projects", "created_at"),
            ("sections", None),
            ("labels", None),
        ]
    )
    def test_partition_keys_are_stable_creation_fields(self, endpoint: str, expected_partition: str | None) -> None:
        # Partition keys must be stable creation timestamps, never a mutable field like updated_at.
        config = TODOIST_ENDPOINTS[endpoint]
        assert config.partition_key == expected_partition
        assert config.partition_key != "updated_at"

    def test_no_endpoint_advertises_incremental_fields(self) -> None:
        # The v1 REST API has no server-side timestamp filter, so nothing advertises incremental fields.
        assert all(fields == [] for fields in INCREMENTAL_FIELDS.values())


class TestTopLevelPagination:
    def test_follows_next_cursor_across_pages(self) -> None:
        responses = {
            f"{BASE}/tasks?limit={PAGE_LIMIT}": [_resp({"results": [{"id": "T1"}], "next_cursor": "c2"})],
            f"{BASE}/tasks?limit={PAGE_LIMIT}&cursor=c2": [_resp({"results": [{"id": "T2"}], "next_cursor": None})],
        }
        rows, params = _run("tasks", responses, _make_manager())
        assert rows == [{"id": "T1"}, {"id": "T2"}]
        assert params[0]["limit"] == PAGE_LIMIT
        assert "cursor" not in params[0]
        assert params[1]["cursor"] == "c2"

    def test_saves_cursor_after_yielding_each_page(self) -> None:
        # State is saved AFTER yielding a page that has a next cursor; the final page saves nothing.
        responses = {
            f"{BASE}/tasks?limit={PAGE_LIMIT}": [_resp({"results": [{"id": "T1"}], "next_cursor": "c2"})],
            f"{BASE}/tasks?limit={PAGE_LIMIT}&cursor=c2": [_resp({"results": [{"id": "T2"}], "next_cursor": None})],
        }
        manager = _make_manager()
        _run("tasks", responses, manager)
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [TodoistResumeConfig(next_cursor="c2")]

    def test_resumes_from_saved_cursor(self) -> None:
        responses = {
            f"{BASE}/tasks?limit={PAGE_LIMIT}&cursor=saved": [_resp({"results": [{"id": "T9"}], "next_cursor": None})],
        }
        rows, params = _run("tasks", responses, _make_manager(TodoistResumeConfig(next_cursor="saved")))
        # Resumes mid-pagination from the saved cursor instead of restarting at page one.
        assert rows == [{"id": "T9"}]
        assert params[0]["cursor"] == "saved"

    def test_empty_first_page_terminates_without_saving(self) -> None:
        responses = {
            f"{BASE}/labels?limit={PAGE_LIMIT}": [_resp({"results": [], "next_cursor": None})],
        }
        manager = _make_manager()
        rows, _params = _run("labels", responses, manager)
        assert rows == []
        manager.save_state.assert_not_called()


class TestCollaboratorsFanOut:
    def test_injects_project_id_onto_every_row(self) -> None:
        responses = {
            f"{BASE}/projects?limit={PAGE_LIMIT}": [
                _resp({"results": [{"id": "P1"}, {"id": "P2"}], "next_cursor": None})
            ],
            f"{BASE}/projects/P1/collaborators?limit={PAGE_LIMIT}": [
                _resp({"results": [{"id": "U1", "name": "Ann"}, {"id": "U2", "name": "Bob"}], "next_cursor": None})
            ],
            f"{BASE}/projects/P2/collaborators?limit={PAGE_LIMIT}": [
                _resp({"results": [{"id": "U1", "name": "Ann"}], "next_cursor": None})
            ],
        }
        rows, _params = _run("collaborators", responses, _make_manager())
        assert rows == [
            {"id": "U1", "name": "Ann", "project_id": "P1"},
            {"id": "U2", "name": "Bob", "project_id": "P1"},
            {"id": "U1", "name": "Ann", "project_id": "P2"},
        ]

    def test_follows_collaborator_pagination(self) -> None:
        responses = {
            f"{BASE}/projects?limit={PAGE_LIMIT}": [_resp({"results": [{"id": "P1"}], "next_cursor": None})],
            f"{BASE}/projects/P1/collaborators?limit={PAGE_LIMIT}": [
                _resp({"results": [{"id": "U1"}], "next_cursor": "next"})
            ],
            f"{BASE}/projects/P1/collaborators?limit={PAGE_LIMIT}&cursor=next": [
                _resp({"results": [{"id": "U2"}], "next_cursor": None})
            ],
        }
        rows, _params = _run("collaborators", responses, _make_manager())
        assert rows == [
            {"id": "U1", "project_id": "P1"},
            {"id": "U2", "project_id": "P1"},
        ]

    def test_project_deleted_mid_fan_out_is_skipped(self) -> None:
        # A project deleted between enumeration and the collaborators fetch 404s — skip it, don't fail.
        responses = {
            f"{BASE}/projects?limit={PAGE_LIMIT}": [
                _resp({"results": [{"id": "P1"}, {"id": "GONE"}, {"id": "P2"}], "next_cursor": None})
            ],
            f"{BASE}/projects/P1/collaborators?limit={PAGE_LIMIT}": [
                _resp({"results": [{"id": "U1"}], "next_cursor": None})
            ],
            f"{BASE}/projects/GONE/collaborators?limit={PAGE_LIMIT}": [_resp({}, status=404)],
            f"{BASE}/projects/P2/collaborators?limit={PAGE_LIMIT}": [
                _resp({"results": [{"id": "U2"}], "next_cursor": None})
            ],
        }
        rows, _params = _run("collaborators", responses, _make_manager())
        assert rows == [
            {"id": "U1", "project_id": "P1"},
            {"id": "U2", "project_id": "P2"},
        ]

    def test_resume_skips_already_completed_project(self) -> None:
        # A project whose collaborators fully synced on the prior attempt is skipped on resume.
        responses = {
            f"{BASE}/projects?limit={PAGE_LIMIT}": [
                _resp({"results": [{"id": "P1"}, {"id": "P2"}], "next_cursor": None})
            ],
            f"{BASE}/projects/P2/collaborators?limit={PAGE_LIMIT}": [
                _resp({"results": [{"id": "U2"}], "next_cursor": None})
            ],
        }
        state = TodoistResumeConfig(
            fanout_state={"completed": ["/projects/P1/collaborators"], "current": None, "child_state": None}
        )
        rows, _params = _run("collaborators", responses, _make_manager(state))
        assert rows == [{"id": "U2", "project_id": "P2"}]

    def test_resume_from_deleted_project_restarts_from_first(self) -> None:
        # The in-progress project from the saved state no longer exists — its checkpoint is ignored and
        # the surviving projects sync fresh (merge dedupes any re-pulled rows).
        responses = {
            f"{BASE}/projects?limit={PAGE_LIMIT}": [_resp({"results": [{"id": "P1"}], "next_cursor": None})],
            f"{BASE}/projects/P1/collaborators?limit={PAGE_LIMIT}": [
                _resp({"results": [{"id": "U1"}], "next_cursor": None})
            ],
        }
        state = TodoistResumeConfig(
            fanout_state={
                "completed": [],
                "current": "/projects/DELETED/collaborators",
                "child_state": {"cursor": "x"},
            }
        )
        rows, _params = _run("collaborators", responses, _make_manager(state))
        assert rows == [{"id": "U1", "project_id": "P1"}]


class TestRetryClassification:
    @parameterized.expand([(500,), (503,), (429,)])
    @mock.patch(SLEEP_PATCH)
    def test_transient_status_is_retried_then_succeeds(self, status: int, _sleep: Any) -> None:
        # 429/5xx are transient — the client backs off and reissues the same request.
        responses = {
            f"{BASE}/tasks?limit={PAGE_LIMIT}": [
                _resp({"error": "transient"}, status=status),
                _resp({"results": [{"id": "T1"}], "next_cursor": None}),
            ],
        }
        rows, _params = _run("tasks", responses, _make_manager())
        assert rows == [{"id": "T1"}]

    @parameterized.expand([(401,), (403,), (404,)])
    @mock.patch(SLEEP_PATCH)
    def test_client_error_fails_loud(self, status: int, _sleep: Any) -> None:
        # 4xx (other than 429) are permanent — raise rather than retry or silently sync 0 rows.
        responses = {
            f"{BASE}/tasks?limit={PAGE_LIMIT}": [_resp({"error": "nope"}, status=status)],
        }
        with pytest.raises(requests.HTTPError):
            _run("tasks", responses, _make_manager())


class TestValidateCredentials:
    @mock.patch(TODOIST_SESSION_PATCH)
    def test_ok(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("tok") is True

    @mock.patch(TODOIST_SESSION_PATCH)
    def test_unauthorized(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("tok") is False

    @mock.patch(TODOIST_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session: Any) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("tok") is False
