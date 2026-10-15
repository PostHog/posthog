from typing import Any, Optional

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vellum import VellumSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.source import VellumSource
from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.vellum import VellumResumeConfig


def _resp(
    status: int = 200,
    *,
    results: Optional[list[dict[str, Any]]] = None,
    count: Optional[int] = None,
    body: Optional[dict[str, Any]] = None,
) -> ScriptedResponse:
    if body is None:
        body = {}
        if results is not None:
            body["results"] = results
        if count is not None:
            body["count"] = count
    return ScriptedResponse(status=status, json=body)


def _run(endpoint: str, script: Script, **kwargs: Any) -> DriveResult:
    driver = SourceDriver(VellumSource(), VellumSourceConfig(api_key="key"))
    return driver.run(endpoint, script, **kwargs)


class TestOffsetPagination:
    def test_resumes_from_saved_offset(self) -> None:
        # A resumed run must skip pages already synced; starting from offset 0 would redo work.
        result = _run(
            "documents",
            [_resp(results=[{"id": "d3"}], count=3)],
            resume_state=VellumResumeConfig(offset=2),
        )

        assert result.params("offset") == ["2"]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _run("documents", [_resp(results=[{"id": "d1"}], count=1)])

        assert result.params("offset") == ["0"]

    def test_checkpoint_saved_after_full_page(self) -> None:
        # After a full page is yielded, the saved offset points at the NEXT page so a crash re-fetches
        # only what wasn't synced; a short page ends the walk without an extra checkpoint.
        page1 = [{"id": f"d_{i}"} for i in range(100)]

        result = _run(
            "documents",
            [_resp(results=page1, count=101), _resp(results=[{"id": "d_last"}], count=101)],
        )

        assert result.saved_states == [VellumResumeConfig(offset=100)]


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_retry(self, _name: str, status_code: int) -> None:
        # 429/5xx must be retried, not surfaced — a transient blip shouldn't fail the sync.
        result = _run(
            "documents",
            [_resp(status=status_code, body={}), _resp(results=[{"id": "d1"}], count=1)],
        )

        assert [r["id"] for r in result.rows] == ["d1"]
        assert len(result.requests) == 2

    def test_client_error_propagates(self) -> None:
        # A 403 (bad/insufficient key) must surface at once so get_non_retryable_errors can stop the sync.
        result = _run("documents", [_resp(status=403, body={"detail": "forbidden"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestExecutionEventsFanOut:
    def test_injects_parent_id_into_every_row(self) -> None:
        # The parent id completes the composite key; without it rows from different deployments that
        # share a span id would collide and every merge would multi-match.
        result = _run(
            "workflow_execution_events",
            [
                _resp(results=[{"id": "A"}, {"id": "B"}], count=2),
                _resp(results=[{"span_id": "s1", "start": "2026-01-01T00:00:00Z"}], count=1),
                _resp(results=[{"span_id": "s2", "start": "2026-01-02T00:00:00Z"}], count=1),
            ],
        )

        assert result.rows == [
            {"workflow_deployment_id": "A", "span_id": "s1", "start": "2026-01-01T00:00:00Z"},
            {"workflow_deployment_id": "B", "span_id": "s2", "start": "2026-01-02T00:00:00Z"},
        ]
        assert result.paths == [
            "/v1/workflow-deployments",
            "/v1/workflow-deployments/A/execution-events",
            "/v1/workflow-deployments/B/execution-events",
        ]

    def test_non_404_error_propagates(self) -> None:
        # Any non-404 child error must fail the whole sync rather than be silently swallowed.
        result = _run(
            "workflow_execution_events",
            [
                _resp(results=[{"id": "A"}], count=1),
                _resp(status=403, body={"detail": "forbidden"}),
            ],
        )

        assert isinstance(result.raised, requests.HTTPError)

    def test_resume_skips_completed_deployment(self) -> None:
        # Resuming with deployment A already recorded complete must not re-walk A — only B is fetched.
        result = _run(
            "workflow_execution_events",
            [
                _resp(results=[{"id": "A"}, {"id": "B"}], count=2),
                _resp(results=[{"span_id": "s2", "start": "2026-01-02T00:00:00Z"}], count=1),
            ],
            resume_state=VellumResumeConfig(
                fanout_state={
                    "completed": ["/workflow-deployments/A/execution-events"],
                    "current": None,
                    "child_state": None,
                }
            ),
        )

        assert result.rows == [{"workflow_deployment_id": "B", "span_id": "s2", "start": "2026-01-02T00:00:00Z"}]
        assert result.paths == ["/v1/workflow-deployments", "/v1/workflow-deployments/B/execution-events"]


class TestSourceResponse:
    @parameterized.expand(
        [
            ("workflow_deployments", ["id"], "created"),
            ("prompt_deployments", ["id"], "created"),
            ("document_indexes", ["id"], "created"),
            ("documents", ["id"], None),
            ("workflow_execution_events", ["workflow_deployment_id", "span_id"], "start"),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, expected_pks: list[str], expected_partition: str | None
    ) -> None:
        response = _run(endpoint, [_resp(results=[], count=0)]).response

        assert response is not None
        assert response.primary_keys == expected_pks
        assert response.partition_keys == ([expected_partition] if expected_partition else None)
        assert response.partition_mode == ("datetime" if expected_partition else None)
        assert response.sort_mode == "asc"
