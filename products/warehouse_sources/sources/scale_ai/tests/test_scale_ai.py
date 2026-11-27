from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.sources.scale_ai._config import ScaleAISourceConfig
from products.warehouse_sources.sources.scale_ai.scale_ai import (
    ScaleAIResumeConfig,
    _build_params,
    _format_incremental_value,
)
from products.warehouse_sources.sources.scale_ai.settings import SCALE_AI_ENDPOINTS
from products.warehouse_sources.sources.scale_ai.source import ScaleAISource
from products.warehouse_sources.sources.sdk import RESTClientRetryableError
from products.warehouse_sources.sources.sdk.testing import (
    DEFAULT_RETRY_ATTEMPTS,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
)


def _docs_response(
    docs: list[dict[str, Any]], next_token: Any = "__unset__", status_code: int = 200
) -> ScriptedResponse:
    body: dict[str, Any] = {"docs": docs}
    if next_token != "__unset__":
        body["next_token"] = next_token
    return ScriptedResponse(status=status_code, json=body)


def _error_response(status_code: int) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, body=b'{"error": "boom"}')


def _driver() -> SourceDriver:
    return SourceDriver(ScaleAISource(), ScaleAISourceConfig(api_key="live_key"))


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "cursor", "cursor"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestBuildParams:
    @parameterized.expand(
        [
            # The chosen incremental field maps to a specific server-side param; the wrong param would
            # silently ignore the cutoff and re-scan the full history every run.
            ("tasks_updated_at", "tasks", "updated_at", "updated_after"),
            ("tasks_created_at", "tasks", "created_at", "start_time"),
            ("batches_created_at", "batches", "created_at", "start_time"),
        ]
    )
    def test_incremental_field_maps_to_server_param(
        self, _name: str, endpoint: str, incremental_field: str, expected_param: str
    ) -> None:
        params = _build_params(
            SCALE_AI_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field=incremental_field,
        )
        assert params[expected_param] == "2026-03-04T00:00:00+00:00"


class TestCursorPagination:
    def test_checkpoints_next_page_token_then_stops(self) -> None:
        result = _driver().run(
            "tasks",
            [
                _docs_response([{"task_id": "T1"}], next_token="tok2"),
                _docs_response([{"task_id": "T2"}], next_token=None),
            ],
        )

        # Checkpoint the token pointing at the next page after page one; the final (null-token) page
        # saves nothing, so a resume re-fetches the saved page (merge dedupes) rather than skipping it.
        assert result.saved_states == [ScaleAIResumeConfig(next_token="tok2")]

    def test_resumes_from_saved_token(self) -> None:
        result = _driver().run(
            "tasks",
            [_docs_response([{"task_id": "T2"}], next_token=None)],
            resume_state=ScaleAIResumeConfig(next_token="tok2"),
        )

        # T1 (first page) is skipped because we resume mid-stream from tok2.
        assert [r["task_id"] for r in result.rows] == ["T2"]
        assert result.requests[0].param("next_token") == "tok2"

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("tasks", [_docs_response([{"task_id": "T1"}], next_token=None)])

        assert result.requests[0].param("next_token") is None


class TestOffsetPagination:
    def test_checkpoints_next_offset_after_full_page(self) -> None:
        full_page = [{"name": f"B{i}"} for i in range(100)]

        result = _driver().run("batches", [_docs_response(full_page), _docs_response([{"name": "B100"}])])

        # Full first page checkpoints the next offset (100); the short second page saves nothing.
        assert result.saved_states == [ScaleAIResumeConfig(offset=100)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "batches", [_docs_response([{"name": "B100"}])], resume_state=ScaleAIResumeConfig(offset=100)
        )

        assert [r["name"] for r in result.rows] == ["B100"]
        assert result.requests[0].param("offset") == "100"

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("batches", [_docs_response([{"name": "B0"}])])

        assert result.requests[0].param("offset") == "0"


def _audits_responder(request: RecordedRequest) -> ScriptedResponse:
    if request.path == "/v1/tasks":
        if request.param("next_token") is None:
            return _docs_response([{"task_id": "T1"}, {"task_id": "T2"}], next_token="tok2")
        return _docs_response([{"task_id": "T3"}], next_token=None)
    task_id = request.path.removeprefix("/v1/audits/task/")
    if task_id == request.path:
        # Any other route must fail the run, not import zero audits.
        return _error_response(404)
    if task_id in ("T2", "T3"):
        return ScriptedResponse(json=[])
    return ScriptedResponse(
        json=[
            {"id": f"A-{task_id}-1", "task_id": task_id, "result": "accepted", "active": False},
            {"id": f"A-{task_id}-2", "task_id": task_id, "result": "rejected", "active": True},
        ]
    )


class TestAuditsFanOut:
    def test_reads_the_audits_of_each_completed_task(self) -> None:
        result = _driver().run("audits", _audits_responder)

        assert result.raised is None
        assert [(r["id"], r["task_id"]) for r in result.rows] == [("A-T1-1", "T1"), ("A-T1-2", "T1")]

        task_requests = [r for r in result.requests if r.path == "/v1/tasks"]
        assert [r.param("next_token") for r in task_requests] == [None, "tok2"]
        assert all(r.param("status") == "completed" and r.param("limit") == "100" for r in task_requests)

        audit_requests = [r for r in result.requests if r.path != "/v1/tasks"]
        assert [r.path for r in audit_requests] == [f"/v1/audits/task/{t}" for t in ("T1", "T2", "T3")]
        # The audits endpoint documents no paging params, so none are sent.
        assert all(r.param("limit") is None for r in audit_requests)

    def test_resume_skips_the_tasks_a_previous_attempt_finished(self) -> None:
        first = _driver().run("audits", _audits_responder)
        assert first.saved_states
        state = first.saved_states[0]
        assert state.fanout_state is not None and state.next_token is None

        resumed = _driver().run("audits", _audits_responder, resume_state=state)

        assert resumed.raised is None
        resumed_paths = [r.path for r in resumed.requests if r.path != "/v1/tasks"]
        assert "/v1/audits/task/T1" not in resumed_paths
        assert "/v1/audits/task/T3" in resumed_paths


class TestBatchStatusesFanOut:
    @parameterized.expand(
        [
            ("plain_name", "kitten_labeling_2020-07", "/v1/batches/kitten_labeling_2020-07/status"),
            # A slash would otherwise split the name into extra path segments.
            ("name_with_slash_and_space", "team a/2026 run", "/v1/batches/team%20a%2F2026%20run/status"),
        ]
    )
    def test_reads_each_batch_status_under_its_name(self, _name: str, batch_name: str, expected_path: str) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v1/batches":
                return _docs_response([{"name": batch_name, "status": "in_progress"}])
            return ScriptedResponse(json={"status": "in_progress", "tasks_pending": 9, "tasks_completed": 1})

        result = _driver().run("batch_statuses", respond)

        assert result.raised is None
        status_requests = [r for r in result.requests if r.path != "/v1/batches"]
        assert [r.path for r in status_requests] == [expected_path]
        assert len(result.rows) == 1
        row = result.rows[0]
        assert row["batch_name"] == batch_name
        assert (row["tasks_pending"], row["tasks_completed"]) == (9, 1)
        assert not any(key.startswith("_") for key in row)


class TestRetryAndErrors:
    def test_retries_exhausted_raises(self) -> None:
        result = _driver().run("tasks", always(_error_response(500)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) >= DEFAULT_RETRY_ATTEMPTS

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_auth_error_is_not_retried(self, _name: str, status_code: int) -> None:
        result = _driver().run("tasks", [_error_response(status_code)])

        assert isinstance(result.raised, Exception)
        assert str(status_code) in str(result.raised)
        assert len(result.requests) == 1


class TestSourceResponse:
    @parameterized.expand([("tasks", ["task_id"]), ("batches", ["name"]), ("projects", ["name"])])
    def test_primary_keys_and_desc_sort(self, endpoint: str, primary_keys: list[str]) -> None:
        # sort_mode="desc" defers watermark persistence to job end — required because tasks filter on
        # updated_at but arrive in created_at order.
        result = _driver().run(endpoint, always(_docs_response([], next_token=None)))

        response = result.response
        assert response is not None
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "desc"
        assert response.partition_keys == ["created_at"]
