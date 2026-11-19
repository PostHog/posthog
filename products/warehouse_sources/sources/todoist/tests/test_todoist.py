from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
)
from products.warehouse_sources.sources.todoist._config import TodoistSourceConfig
from products.warehouse_sources.sources.todoist.settings import (
    COMPLETED_TASKS_EARLIEST,
    COMPLETED_TASKS_WINDOW,
    INCREMENTAL_FIELDS,
    TODOIST_ENDPOINTS,
    TodoistFanOut,
)
from products.warehouse_sources.sources.todoist.source import TodoistSource
from products.warehouse_sources.sources.todoist.todoist import PAGE_LIMIT, TodoistResumeConfig

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
    endpoint: str,
    responses_by_url: dict[str, list[ScriptedResponse]],
    resume: TodoistResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    driver = SourceDriver(TodoistSource(), TodoistSourceConfig(api_token="tok"))
    return driver.run(endpoint, _by_url(responses_by_url), resume_state=resume, **inputs)


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
        assert config.fan_out == TodoistFanOut(parent="projects", parent_id_column="project_id")
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

    def test_only_endpoints_with_a_server_side_time_filter_advertise_incremental_fields(self) -> None:
        incremental = {name: [f["field"] for f in fields] for name, fields in INCREMENTAL_FIELDS.items() if fields}
        assert incremental == {"completed_tasks": ["completed_at"], "activities": ["event_date"]}


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


NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestCompletedTasksWindows:
    @time_machine.travel(NOW, tick=False)
    def test_full_refresh_sweeps_bounded_windows_from_the_earliest_date_to_now(self) -> None:
        driver = SourceDriver(TodoistSource(), TodoistSourceConfig(api_token="tok"))
        result = driver.run("completed_tasks", always(_resp({"items": [], "next_cursor": None})))

        assert result.raised is None
        windows = [
            (datetime.fromisoformat(r.param("since") or ""), datetime.fromisoformat(r.param("until") or ""))
            for r in result.requests
        ]
        assert windows[0][0] == COMPLETED_TASKS_EARLIEST
        assert windows[-1][1] == NOW
        assert all(since < until <= since + COMPLETED_TASKS_WINDOW for since, until in windows)
        # Contiguous windows: no completion time falls in a gap or in two windows.
        assert all(prev[1] == nxt[0] for prev, nxt in zip(windows, windows[1:]))

    @time_machine.travel(NOW, tick=False)
    def test_incremental_starts_at_the_watermark_and_pages_each_window(self) -> None:
        last_value = NOW - timedelta(days=100)
        first_until = last_value + COMPLETED_TASKS_WINDOW
        path = f"{BASE}/tasks/completed/by_completion_date"
        first = f"{path}?since={_iso(last_value)}&until={_iso(first_until)}&limit={PAGE_LIMIT}"
        second = f"{path}?since={_iso(first_until)}&until={_iso(NOW)}&limit={PAGE_LIMIT}"
        responses = {
            first: [_resp({"items": [{"id": "T1", "completed_at": "a"}], "next_cursor": "c2"})],
            f"{first}&cursor=c2": [_resp({"items": [{"id": "T2", "completed_at": "b"}], "next_cursor": None})],
            second: [_resp({"items": [{"id": "T3", "completed_at": "c"}], "next_cursor": None})],
        }
        result = _run(
            "completed_tasks", responses, incremental_field="completed_at", db_incremental_field_last_value=last_value
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["T1", "T2", "T3"]

    @time_machine.travel(NOW, tick=False)
    def test_resumes_the_saved_window_with_its_cursor_then_continues(self) -> None:
        # The earlier attempt ended its last window at its own "now", which is before this run's.
        since = NOW - timedelta(days=30)
        until = NOW - timedelta(days=10)
        path = f"{BASE}/tasks/completed/by_completion_date"
        responses = {
            f"{path}?since={_iso(since)}&until={_iso(until)}&limit={PAGE_LIMIT}&cursor=saved": [
                _resp({"items": [{"id": "T9", "completed_at": "a"}], "next_cursor": None})
            ],
            f"{path}?since={_iso(until)}&until={_iso(NOW)}&limit={PAGE_LIMIT}": [
                _resp({"items": [{"id": "T10", "completed_at": "b"}], "next_cursor": None})
            ],
        }
        resume = TodoistResumeConfig(next_cursor="saved", window_since=_iso(since), window_until=_iso(until))
        result = _run("completed_tasks", responses, resume)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["T9", "T10"]


class TestActivities:
    @parameterized.expand(
        [
            ("full_refresh", {}, None),
            (
                "incremental",
                {
                    "incremental_field": "event_date",
                    "db_incremental_field_last_value": datetime(2026, 5, 1, tzinfo=UTC),
                },
                "2026-05-01T00:00:00Z",
            ),
        ]
    )
    def test_date_from_is_sent_only_on_incremental_syncs(
        self, _name: str, inputs: dict[str, Any], expected_date_from: str | None
    ) -> None:
        driver = SourceDriver(TodoistSource(), TodoistSourceConfig(api_token="tok"))
        result = driver.run(
            "activities",
            always(_resp({"results": [{"object_id": "1", "event_type": "added"}], "next_cursor": None})),
            **inputs,
        )

        assert result.raised is None
        assert result.requests[0].param("date_from") == expected_date_from
        assert result.requests[0].param("date_to") is None


class TestCommentsFanOut:
    def test_task_comments_skip_tasks_without_comments_and_follow_every_page(self) -> None:
        responses = {
            f"{BASE}/tasks?limit={PAGE_LIMIT}": [
                _resp(
                    {
                        "results": [{"id": "T1", "note_count": 3}, {"id": "T2", "note_count": 0}, {"id": "T3"}],
                        "next_cursor": None,
                    }
                )
            ],
            f"{BASE}/comments?task_id=T1&limit={PAGE_LIMIT}": [
                _resp({"results": [{"id": "C1"}, {"id": "C2"}], "next_cursor": "c2"})
            ],
            f"{BASE}/comments?task_id=T1&limit={PAGE_LIMIT}&cursor=c2": [
                _resp({"results": [{"id": "C3"}], "next_cursor": None})
            ],
            f"{BASE}/comments?task_id=T3&limit={PAGE_LIMIT}": [_resp({"results": [{"id": "C4"}], "next_cursor": None})],
        }
        result = _run("comments", responses)

        assert result.raised is None
        assert result.rows == [
            {"id": "C1", "task_id": "T1"},
            {"id": "C2", "task_id": "T1"},
            {"id": "C3", "task_id": "T1"},
            {"id": "C4", "task_id": "T3"},
        ]

    def test_project_comments_inject_project_id(self) -> None:
        responses = {
            f"{BASE}/projects?limit={PAGE_LIMIT}": [
                _resp({"results": [{"id": "P1"}, {"id": "P2"}], "next_cursor": None})
            ],
            f"{BASE}/comments?project_id=P1&limit={PAGE_LIMIT}": [
                _resp({"results": [{"id": "C1"}], "next_cursor": None})
            ],
            f"{BASE}/comments?project_id=P2&limit={PAGE_LIMIT}": [_resp({"results": [], "next_cursor": None})],
        }
        result = _run("project_comments", responses)

        assert result.raised is None
        assert result.rows == [{"id": "C1", "project_id": "P1"}]
