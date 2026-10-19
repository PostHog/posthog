from collections.abc import Callable
from typing import Any

from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nebiusai import (
    NebiusAISourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai import nebius_ai
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.nebius_ai import (
    NEBIUS_AI_BASE_URL,
    NebiusAIResumeConfig,
    NebiusAIRetryableError,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.source import NebiusAISource


def _driver(api_key: str = "nbk_test") -> SourceDriver:
    return SourceDriver(NebiusAISource(), NebiusAISourceConfig(api_key=api_key))


def _answer_by_url(pages: dict[str, Any]) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        return ScriptedResponse(json=pages[request.url])

    return respond


JOBS_URL = f"{NEBIUS_AI_BASE_URL}/fine_tuning/jobs"
EVENTS_PAGES = {
    f"{JOBS_URL}?limit=100": {"data": [{"id": "job-a"}, {"id": "job-b"}], "has_more": True, "last_id": "job-b"},
    f"{JOBS_URL}?limit=100&after=job-b": {"data": [{"id": "job-c"}], "has_more": False},
    f"{JOBS_URL}/job-a/events?limit=100": {"data": [{"id": "ev1", "created_at": 3}], "has_more": True},
    f"{JOBS_URL}/job-a/events?limit=100&after=ev1": {"data": [{"id": "ev2", "created_at": 2}], "has_more": False},
    f"{JOBS_URL}/job-b/events?limit=100": {"data": [], "has_more": False},
    f"{JOBS_URL}/job-c/events?limit=100": {"data": [{"id": "ev1", "created_at": 1}], "has_more": False},
}


class TestPerFineTuningJobEndpoints:
    def test_walks_every_job_page_and_child_page_staging_the_next_position_before_each_yield(self) -> None:
        result = _driver().run("fine_tuning_job_events", _answer_by_url(EVENTS_PAGES))

        assert result.raised is None
        assert [(r["fine_tuning_job_id"], r["id"]) for r in result.rows] == [
            ("job-a", "ev1"),
            ("job-a", "ev2"),
            ("job-c", "ev1"),
        ]
        assert result.committed_states == [
            NebiusAIResumeConfig(job_id="job-a", after="ev1"),
            NebiusAIResumeConfig(job_id="job-b"),
            NebiusAIResumeConfig(jobs_after="job-b"),
        ]

    @parameterized.expand(
        [
            (
                "mid_job_child_page",
                NebiusAIResumeConfig(job_id="job-a", after="ev1"),
                [("job-a", "ev2"), ("job-c", "ev1")],
            ),
            (
                "job_deleted_since_cursor_was_saved",
                NebiusAIResumeConfig(job_id="job-gone", after="ev9"),
                [("job-a", "ev1"), ("job-a", "ev2"), ("job-c", "ev1")],
            ),
            ("later_job_page", NebiusAIResumeConfig(jobs_after="job-b"), [("job-c", "ev1")]),
        ]
    )
    def test_resumes_from_saved_position(
        self, _name: str, state: NebiusAIResumeConfig, expected: list[tuple[str, str]]
    ) -> None:
        result = _driver().run("fine_tuning_job_events", _answer_by_url(EVENTS_PAGES), resume_state=state)

        assert result.raised is None
        assert [(r["fine_tuning_job_id"], r["id"]) for r in result.rows] == expected


OPERATIONS_URL = f"{NEBIUS_AI_BASE_URL}/operations"


class TestOperationsTimeCursor:
    @mock.patch.object(nebius_ai, "PAGE_SIZE", 2)
    def test_pages_by_created_at_cursor_and_drops_repeated_boundary_rows(self) -> None:
        pages = {
            f"{OPERATIONS_URL}?limit=2": {"data": [{"id": "op3", "created_at": 300}, {"id": "op2", "created_at": 200}]},
            f"{OPERATIONS_URL}?limit=2&cursor_time=1970-01-01T00%3A03%3A20%2B00%3A00": {
                "data": [{"id": "op2", "created_at": 200}, {"id": "op1", "created_at": 100}]
            },
            f"{OPERATIONS_URL}?limit=2&cursor_time=1970-01-01T00%3A01%3A40%2B00%3A00": {
                "data": [{"id": "op1", "created_at": 100}]
            },
        }

        result = _driver().run("operations", _answer_by_url(pages))

        assert result.raised is None
        assert [r["id"] for r in result.rows] == ["op3", "op2", "op1"]

    @parameterized.expand(
        [
            ("same_timestamp_page", [{"id": "op2", "created_at": 200}, {"id": "op1", "created_at": 200}]),
            ("cursor_moves_forward", [{"id": "op4", "created_at": 400}, {"id": "op5", "created_at": 500}]),
        ]
    )
    @mock.patch.object(nebius_ai, "PAGE_SIZE", 2)
    def test_full_page_whose_cursor_does_not_move_back_fails_the_sync(
        self, _name: str, second_page: list[dict[str, Any]]
    ) -> None:
        pages = {
            f"{OPERATIONS_URL}?limit=2": {"data": [{"id": "op3", "created_at": 300}, {"id": "op2", "created_at": 200}]},
            f"{OPERATIONS_URL}?limit=2&cursor_time=1970-01-01T00%3A03%3A20%2B00%3A00": {"data": second_page},
        }

        result = _driver().run("operations", _answer_by_url(pages))

        assert isinstance(result.raised, nebius_ai.NebiusAIPaginationError)


class TestValidateCredentials:
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_auth_failure_is_rejected_with_message(self, _name: str, status_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            ok, message = validate_credentials("nbk_test")
        assert ok is False
        assert message
        assert network.requests_log[0].path == "/v1/models"

    @parameterized.expand([("network_error", None), ("server_error", 503), ("rate_limited", 429)])
    def test_transient_failure_is_not_reported_as_invalid_key(self, _name: str, status_code: int | None) -> None:
        # A blip must never be surfaced as an invalid key — that would send the user to rotate a good one.
        answer = ConnectionResetError("boom") if status_code is None else ScriptedResponse(status=status_code)
        with scripted_network(always(answer)) as network:
            ok, message = validate_credentials("nbk_test")
        assert ok is False
        assert message is not None
        assert "invalid" not in message.lower()
        assert {request.path for request in network.requests_log} == {"/v1/models"}

    def test_probe_redacts_key_and_disables_redirects(self) -> None:
        # The key must stay out of captured samples, and a 30x must not replay the bearer token.
        with scripted_network([ScriptedResponse(json={"data": []})]) as network:
            assert validate_credentials("nbk_secret") == (True, None)
        assert network.session_options == [{"redact_values": ("nbk_secret",), "allow_redirects": False}]
        assert network.requests_log[0].headers["authorization"] == "Bearer nbk_secret"


class TestNonPaginatedEndpoint:
    def test_models_yields_full_list_in_one_batch(self) -> None:
        # /models returns the whole list in a single response; it must not be paged with after/limit.
        result = _driver().run(
            "models",
            [
                ScriptedResponse(
                    json={
                        "object": "list",
                        "data": [
                            {"id": "meta-llama/Llama-3.3-70B", "created": 1700000000, "owned_by": "nebius"},
                            {"id": "deepseek-ai/DeepSeek-V3", "created": 1710000000, "owned_by": "nebius"},
                        ],
                    }
                )
            ],
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["meta-llama/Llama-3.3-70B", "deepseek-ai/DeepSeek-V3"]
        assert len(result.items) == 1
        assert result.paths == ["/v1/models"]
        assert result.queries == [{}]
        # A single-shot endpoint has nothing to resume from, so it must never persist a cursor.
        assert result.saved_states == []


class TestCursorPagination:
    def test_falls_back_to_last_item_id_when_last_id_absent(self) -> None:
        # Some OpenAI-compatible responses only return has_more; the cursor must come from the row id.
        result = _driver().run(
            "files",
            [
                ScriptedResponse(json={"data": [{"id": "f1", "created_at": 1}], "has_more": True}),
                ScriptedResponse(json={"data": [{"id": "f2", "created_at": 2}], "has_more": False}),
            ],
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["f1", "f2"]
        assert result.params("limit") == ["100", "100"]
        assert result.params("after") == [None, "f1"]
        assert result.saved_states == [NebiusAIResumeConfig(after="f1")]

    def test_missing_primary_key_on_paginated_page_fails_loudly(self) -> None:
        # A page that claims has_more but whose final row is missing its `id` must raise, not silently
        # drop every later page by treating the malformed page as terminal.
        result = _driver().run("files", [ScriptedResponse(json={"data": [{"created_at": 1}], "has_more": True})])
        assert isinstance(result.raised, KeyError)
        assert result.paths == ["/v1/files"]
        assert result.params("limit") == ["100"]


class TestSessionHardening:
    def test_get_rows_session_redacts_key_and_disables_redirects(self) -> None:
        # The long-lived paging session must mask the key and refuse redirects so a 30x can't replay
        # the bearer token to another origin.
        result = _driver("nbk_secret").run("models", [ScriptedResponse(json={"data": []})])
        assert result.raised is None
        assert result.session_options == [{"redact_values": ("nbk_secret",), "allow_redirects": False}]
        assert result.requests[0].headers["authorization"] == "Bearer nbk_secret"


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("bad_gateway", 502), ("server_error", 500)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status_code: int) -> None:
        result = _driver().run("models", always(ScriptedResponse(status=status_code)))
        assert isinstance(result.raised, NebiusAIRetryableError)
        assert len(result.requests) >= 5
        assert {request.path for request in result.requests} == {"/v1/models"}

    def test_client_error_raises_for_status(self) -> None:
        result = _driver().run("models", [ScriptedResponse(status=401)])
        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/v1/models"]

    def test_transient_error_retried_then_succeeds(self) -> None:
        result = _driver().run("models", [requests.ReadTimeout("timeout"), ScriptedResponse(json={"data": []})])
        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) >= 2
        assert {request.path for request in result.requests} == {"/v1/models"}


class TestSourceResponse:
    @parameterized.expand(
        [
            ("models", "created", ["id"]),
            ("files", "created_at", ["id"]),
            ("batches", "created_at", ["id"]),
            ("fine_tuning_jobs", "created_at", ["id"]),
            ("fine_tuning_job_events", "created_at", ["fine_tuning_job_id", "id"]),
            ("fine_tuning_job_checkpoints", "created_at", ["fine_tuning_job_id", "id"]),
            ("datasets", "created_at", ["id"]),
            ("operations", "created_at", ["id"]),
        ]
    )
    def test_partition_and_pk_per_endpoint(self, endpoint: str, partition_key: str, primary_keys: list[str]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={"data": []})])
        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == primary_keys
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == [partition_key]
        # These OpenAI-style list endpoints return newest-first.
        assert result.response.sort_mode == "desc"
