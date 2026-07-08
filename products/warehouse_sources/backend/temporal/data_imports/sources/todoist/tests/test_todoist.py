from typing import Any

from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.todoist import todoist
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.settings import (
    INCREMENTAL_FIELDS,
    TODOIST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.todoist import (
    PAGE_LIMIT,
    TodoistResumeConfig,
    _build_url,
    _parse_page,
    get_rows,
    todoist_source,
)


class _FakeResumableManager:
    def __init__(self, state: TodoistResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[TodoistResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> TodoistResumeConfig | None:
        return self._state

    def save_state(self, data: TodoistResumeConfig) -> None:
        self.saved.append(data)


def _response_with_status(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    return response


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("/tasks", {}) == "https://api.todoist.com/api/v1/tasks"

    def test_with_params_is_encoded(self) -> None:
        # Cursors can contain characters that must be percent-encoded.
        assert _build_url("/tasks", {"limit": 200, "cursor": "a b/c"}) == (
            "https://api.todoist.com/api/v1/tasks?limit=200&cursor=a+b%2Fc"
        )


class TestParsePage:
    @parameterized.expand(
        [
            (
                "wrapped_shape_with_cursor",
                {"results": [{"id": "1"}, {"id": "2"}], "next_cursor": "abc"},
                [{"id": "1"}, {"id": "2"}],
                "abc",
            ),
            (
                "wrapped_shape_last_page",
                {"results": [{"id": "1"}], "next_cursor": None},
                [{"id": "1"}],
                None,
            ),
            ("bare_array_has_no_cursor", [{"id": "1"}, {"id": "2"}], [{"id": "1"}, {"id": "2"}], None),
            ("empty_wrapped", {"results": [], "next_cursor": None}, [], None),
        ]
    )
    def test_parse_page(self, _name: str, data: Any, expected_rows: list[dict], expected_cursor: str | None) -> None:
        rows, cursor = _parse_page(data)
        assert rows == expected_rows
        assert cursor == expected_cursor


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


class TestSourceResponse:
    @parameterized.expand(
        [
            ("tasks", ["id"], "datetime", "added_at"),
            ("projects", ["id"], "datetime", "created_at"),
            ("sections", ["id"], None, None),
            ("labels", ["id"], None, None),
            ("collaborators", ["project_id", "id"], None, None),
        ]
    )
    def test_source_response_shape(
        self,
        endpoint: str,
        expected_keys: list[str],
        expected_partition_mode: str | None,
        expected_partition_key: str | None,
    ) -> None:
        response = todoist_source(
            api_token="tok",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.partition_mode == expected_partition_mode
        assert response.partition_keys == ([expected_partition_key] if expected_partition_key else None)
        # Ascending order is the safe default; we never declare desc here.
        assert response.sort_mode == "asc"


def _collect(manager: _FakeResumableManager, monkeypatch: Any, endpoint: str, pages: dict[str, Any]) -> list[dict]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(todoist, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for batch in get_rows(
        api_token="tok",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(batch)
    return rows


class TestTopLevelPagination:
    def test_follows_next_cursor_across_pages(self, monkeypatch: Any) -> None:
        pages = {
            f"https://api.todoist.com/api/v1/tasks?limit={PAGE_LIMIT}": {
                "results": [{"id": "T1"}],
                "next_cursor": "c2",
            },
            f"https://api.todoist.com/api/v1/tasks?limit={PAGE_LIMIT}&cursor=c2": {
                "results": [{"id": "T2"}],
                "next_cursor": None,
            },
        }
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, "tasks", pages)
        assert rows == [{"id": "T1"}, {"id": "T2"}]

    def test_saves_cursor_after_yielding_each_page(self, monkeypatch: Any) -> None:
        # State must be saved AFTER yielding so a crash re-yields the last page rather than skipping it.
        pages = {
            f"https://api.todoist.com/api/v1/tasks?limit={PAGE_LIMIT}": {
                "results": [{"id": "T1"}],
                "next_cursor": "c2",
            },
            f"https://api.todoist.com/api/v1/tasks?limit={PAGE_LIMIT}&cursor=c2": {
                "results": [{"id": "T2"}],
                "next_cursor": None,
            },
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, "tasks", pages)
        # Only one save: after the first page (which has a next cursor). The last page has none.
        assert [s.next_cursor for s in manager.saved] == ["c2"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        pages = {
            f"https://api.todoist.com/api/v1/tasks?limit={PAGE_LIMIT}&cursor=saved": {
                "results": [{"id": "T9"}],
                "next_cursor": None,
            },
        }
        manager = _FakeResumableManager(TodoistResumeConfig(next_cursor="saved"))
        rows = _collect(manager, monkeypatch, "tasks", pages)
        # Resumes mid-pagination from the saved cursor instead of restarting at page one.
        assert rows == [{"id": "T9"}]

    def test_empty_first_page_terminates(self, monkeypatch: Any) -> None:
        pages: dict[str, Any] = {
            f"https://api.todoist.com/api/v1/labels?limit={PAGE_LIMIT}": {"results": [], "next_cursor": None},
        }
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, "labels", pages)
        assert rows == []
        assert manager.saved == []


class TestCollaboratorsFanOut:
    def test_injects_project_id_onto_every_row(self, monkeypatch: Any) -> None:
        pages = {
            f"https://api.todoist.com/api/v1/projects?limit={PAGE_LIMIT}": {
                "results": [{"id": "P1"}, {"id": "P2"}],
                "next_cursor": None,
            },
            f"https://api.todoist.com/api/v1/projects/P1/collaborators?limit={PAGE_LIMIT}": {
                "results": [{"id": "U1", "name": "Ann"}, {"id": "U2", "name": "Bob"}],
                "next_cursor": None,
            },
            f"https://api.todoist.com/api/v1/projects/P2/collaborators?limit={PAGE_LIMIT}": {
                "results": [{"id": "U1", "name": "Ann"}],
                "next_cursor": None,
            },
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, "collaborators", pages)
        assert rows == [
            {"id": "U1", "name": "Ann", "project_id": "P1"},
            {"id": "U2", "name": "Bob", "project_id": "P1"},
            {"id": "U1", "name": "Ann", "project_id": "P2"},
        ]

    def test_follows_collaborator_pagination(self, monkeypatch: Any) -> None:
        pages = {
            f"https://api.todoist.com/api/v1/projects?limit={PAGE_LIMIT}": {
                "results": [{"id": "P1"}],
                "next_cursor": None,
            },
            f"https://api.todoist.com/api/v1/projects/P1/collaborators?limit={PAGE_LIMIT}": {
                "results": [{"id": "U1"}],
                "next_cursor": "next",
            },
            f"https://api.todoist.com/api/v1/projects/P1/collaborators?limit={PAGE_LIMIT}&cursor=next": {
                "results": [{"id": "U2"}],
                "next_cursor": None,
            },
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, "collaborators", pages)
        assert rows == [
            {"id": "U1", "project_id": "P1"},
            {"id": "U2", "project_id": "P1"},
        ]

    def test_project_deleted_mid_fan_out_is_skipped(self, monkeypatch: Any) -> None:
        not_found = requests.HTTPError(response=_response_with_status(404))
        pages = {
            f"https://api.todoist.com/api/v1/projects?limit={PAGE_LIMIT}": {
                "results": [{"id": "P1"}, {"id": "GONE"}, {"id": "P2"}],
                "next_cursor": None,
            },
            f"https://api.todoist.com/api/v1/projects/P1/collaborators?limit={PAGE_LIMIT}": {
                "results": [{"id": "U1"}],
                "next_cursor": None,
            },
            f"https://api.todoist.com/api/v1/projects/GONE/collaborators?limit={PAGE_LIMIT}": not_found,
            f"https://api.todoist.com/api/v1/projects/P2/collaborators?limit={PAGE_LIMIT}": {
                "results": [{"id": "U2"}],
                "next_cursor": None,
            },
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, "collaborators", pages)
        assert rows == [
            {"id": "U1", "project_id": "P1"},
            {"id": "U2", "project_id": "P2"},
        ]

    def test_resume_from_deleted_project_restarts_from_first(self, monkeypatch: Any) -> None:
        pages = {
            f"https://api.todoist.com/api/v1/projects?limit={PAGE_LIMIT}": {
                "results": [{"id": "P1"}],
                "next_cursor": None,
            },
            f"https://api.todoist.com/api/v1/projects/P1/collaborators?limit={PAGE_LIMIT}": {
                "results": [{"id": "U1"}],
                "next_cursor": None,
            },
        }
        manager = _FakeResumableManager(TodoistResumeConfig(next_cursor=None, project_id="DELETED"))
        rows = _collect(manager, monkeypatch, "collaborators", pages)
        assert rows == [{"id": "U1", "project_id": "P1"}]


class TestFetchPageRetryClassification:
    # Call the undecorated function so we assert classification without tenacity's backoff sleeps.
    _fetch = staticmethod(todoist._fetch_page.__wrapped__)  # type: ignore[attr-defined]

    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_statuses_raise_retryable_error(self, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(status_code)
        try:
            self._fetch(session, "https://api.todoist.com/api/v1/tasks", {}, MagicMock())
        except todoist.TodoistRetryableError:
            return
        raise AssertionError("expected TodoistRetryableError to be raised")

    @parameterized.expand([(401,), (403,), (404,)])
    def test_client_errors_raise_http_error(self, status_code: int) -> None:
        # 4xx (other than 429) are permanent — raise_for_status, not a retryable error.
        session = MagicMock()
        session.get.return_value = _response_with_status(status_code)
        try:
            self._fetch(session, "https://api.todoist.com/api/v1/tasks", {}, MagicMock())
        except todoist.TodoistRetryableError as exc:
            raise AssertionError("client errors must not be classified retryable") from exc
        except requests.HTTPError:
            return
        raise AssertionError("expected HTTPError to be raised")

    def test_success_returns_json_body(self) -> None:
        session = MagicMock()
        body: dict[str, Any] = {"results": [], "next_cursor": None}
        session.get.return_value = MagicMock(status_code=200, ok=True, **{"json.return_value": body})
        assert self._fetch(session, "https://api.todoist.com/api/v1/tasks", {}, MagicMock()) == body
