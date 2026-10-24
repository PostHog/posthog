from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.todoist import (
    TodoistSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.settings import (
    INCREMENTAL_FIELDS,
    TODOIST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.source import TodoistSource
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.todoist import (
    PAGE_LIMIT,
    TodoistResumeConfig,
)

BASE = "https://api.todoist.com/api/v1"


def _resp(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _norm(url: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    parts = urlsplit(url)
    return parts.path, tuple(sorted(parse_qsl(parts.query)))


def _by_url(responses_by_url: dict[str, list[ScriptedResponse]]) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Resolve each request by its fully-encoded URL.

    Values are per-URL queues so a URL can return different responses across retries/pages.
    """
    normalized = {_norm(url): list(queue) for url, queue in responses_by_url.items()}

    def respond(request: RecordedRequest) -> ScriptedResponse:
        queue = normalized.get(_norm(request.url))
        if not queue:
            raise UnexpectedRequest(f"unexpected request url {request.url!r}")
        return queue.pop(0)

    return respond


def _run(
    endpoint: str, responses_by_url: dict[str, list[ScriptedResponse]], resume: TodoistResumeConfig | None = None
) -> DriveResult:
    driver = SourceDriver(TodoistSource(), TodoistSourceConfig(api_token="tok"))
    return driver.run(endpoint, _by_url(responses_by_url), resume_state=resume)


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
    def test_source_response_shape(
        self,
        endpoint: str,
        expected_keys: list[str],
        expected_partition_mode: str | None,
        expected_partition_key: str | None,
    ) -> None:
        driver = SourceDriver(TodoistSource(), TodoistSourceConfig(api_token="tok"))
        result = driver.run(endpoint, always(_resp({"results": [], "next_cursor": None})))

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.partition_mode == expected_partition_mode
        assert response.partition_keys == ([expected_partition_key] if expected_partition_key else None)
        assert response.sort_mode is None


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
        result = _run("tasks", responses)
        assert result.rows == [{"id": "T1"}, {"id": "T2"}]
        assert result.requests[0].param("limit") == str(PAGE_LIMIT)
        assert result.requests[0].param("cursor") is None
        assert result.requests[1].param("cursor") == "c2"

    def test_resumes_from_saved_cursor(self) -> None:
        responses = {
            f"{BASE}/tasks?limit={PAGE_LIMIT}&cursor=saved": [_resp({"results": [{"id": "T9"}], "next_cursor": None})],
        }
        result = _run("tasks", responses, TodoistResumeConfig(next_cursor="saved"))
        # Resumes mid-pagination from the saved cursor instead of restarting at page one.
        assert result.rows == [{"id": "T9"}]
        assert result.requests[0].param("cursor") == "saved"


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
        result = _run("collaborators", responses)
        assert result.rows == [
            {"id": "U1", "name": "Ann", "project_id": "P1"},
            {"id": "U2", "name": "Bob", "project_id": "P1"},
            {"id": "U1", "name": "Ann", "project_id": "P2"},
        ]

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
        result = _run("collaborators", responses, state)
        assert result.rows == [{"id": "U1", "project_id": "P1"}]


class TestRetryClassification:
    @parameterized.expand([(500,), (503,), (429,)])
    def test_transient_status_is_retried_then_succeeds(self, status: int) -> None:
        # 429/5xx are transient — the client backs off and reissues the same request.
        responses = {
            f"{BASE}/tasks?limit={PAGE_LIMIT}": [
                _resp({"error": "transient"}, status=status),
                _resp({"results": [{"id": "T1"}], "next_cursor": None}),
            ],
        }
        result = _run("tasks", responses)
        assert result.rows == [{"id": "T1"}]

    @parameterized.expand([(401,), (403,), (404,)])
    def test_client_error_fails_loud(self, status: int) -> None:
        # 4xx (other than 429) are permanent — raise rather than retry or silently sync 0 rows.
        responses = {
            f"{BASE}/tasks?limit={PAGE_LIMIT}": [_resp({"error": "nope"}, status=status)],
        }
        result = _run("tasks", responses)
        assert isinstance(result.raised, requests.HTTPError)
