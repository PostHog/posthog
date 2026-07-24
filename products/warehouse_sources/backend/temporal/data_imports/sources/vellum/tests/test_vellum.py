import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.settings import VELLUM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.vellum import (
    VellumResumeConfig,
    vellum_source,
)

# vellum builds the tracked session (capture=False) in its own module and hands it to RESTClient via
# client_config["session"], so patch it there rather than in rest_client.
SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.vellum.vellum.make_tracked_session"
# tenacity sleeps between client retries; patch its clock so retryable-status tests don't wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"

BASE = "https://api.vellum.ai/v1"
DOCUMENTS_URL = f"{BASE}/documents"
WFD_URL = f"{BASE}/workflow-deployments"
EVENTS_A = f"{BASE}/workflow-deployments/A/execution-events"
EVENTS_B = f"{BASE}/workflow-deployments/B/execution-events"


def _resp(
    status: int = 200,
    *,
    results: Optional[list[dict[str, Any]]] = None,
    count: Optional[int] = None,
    body: Optional[dict[str, Any]] = None,
    url: str = DOCUMENTS_URL,
) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp.url = url
    resp.reason = "OK" if status < 400 else "Error"
    if body is None:
        body = {}
        if results is not None:
            body["results"] = results
        if count is not None:
            body["count"] = count
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: VellumResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[requests.Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each request
    is prepared instead of inspecting the final state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(endpoint: str, manager: mock.MagicMock) -> Any:
    return vellum_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestOffsetPagination:
    @mock.patch(SESSION_PATCH)
    def test_walks_offsets_and_stops_at_count(self, MockSession) -> None:
        # offset must advance by the page size and pagination must stop once offset reaches `count`.
        session = MockSession.return_value
        page1 = [{"id": f"d_{i}"} for i in range(100)]
        params = _wire(session, [_resp(results=page1, count=101), _resp(results=[{"id": "d_last"}], count=101)])

        rows = _rows(_run("documents", _make_manager()))

        assert [r["id"] for r in rows] == [*(f"d_{i}" for i in range(100)), "d_last"]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == 100
        assert params[1]["offset"] == 100

    @mock.patch(SESSION_PATCH)
    def test_stops_on_short_page(self, MockSession) -> None:
        # A short (below-limit) page is the last page — the accumulated rows are all that exist.
        session = MockSession.return_value
        _wire(session, [_resp(results=[{"id": "d1"}], count=1)])

        rows = _rows(_run("documents", _make_manager()))
        assert [r["id"] for r in rows] == ["d1"]
        assert session.send.call_count == 1

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        # A resumed run must skip pages already synced; starting from offset 0 would redo work.
        session = MockSession.return_value
        params = _wire(session, [_resp(results=[{"id": "d3"}], count=3)])

        _rows(_run("documents", _make_manager(VellumResumeConfig(offset=2))))
        assert params[0]["offset"] == 2

    @mock.patch(SESSION_PATCH)
    def test_checkpoint_saved_after_full_page(self, MockSession) -> None:
        # After a full page is yielded, the saved offset points at the NEXT page so a crash re-fetches
        # only what wasn't synced; a short page ends the walk without an extra checkpoint.
        session = MockSession.return_value
        page1 = [{"id": f"d_{i}"} for i in range(100)]
        _wire(session, [_resp(results=page1, count=101), _resp(results=[{"id": "d_last"}], count=101)])

        manager = _make_manager()
        _rows(_run("documents", manager))

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == VellumResumeConfig(offset=100)

    @mock.patch(SESSION_PATCH)
    def test_ordering_param_sent_when_configured(self, MockSession) -> None:
        # workflow_deployments paginates oldest-first via ?ordering=created for a stable page order.
        session = MockSession.return_value
        params = _wire(session, [_resp(results=[], count=0, url=WFD_URL)])
        _rows(_run("workflow_deployments", _make_manager()))
        assert params[0]["ordering"] == "created"

    @mock.patch(SESSION_PATCH)
    def test_ordering_param_absent_for_unordered_endpoint(self, MockSession) -> None:
        # documents exposes no stable created field, so no ordering is forced.
        session = MockSession.return_value
        params = _wire(session, [_resp(results=[], count=0)])
        _rows(_run("documents", _make_manager()))
        assert "ordering" not in params[0]


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch(SLEEP_PATCH, return_value=None)
    @mock.patch(SESSION_PATCH)
    def test_retryable_status_codes_retry(self, _name: str, status_code: int, MockSession, _sleep) -> None:
        # 429/5xx must be retried, not surfaced — a transient blip shouldn't fail the sync.
        session = MockSession.return_value
        _wire(session, [_resp(status=status_code, body={}), _resp(results=[{"id": "d1"}], count=1)])

        rows = _rows(_run("documents", _make_manager()))
        assert [r["id"] for r in rows] == ["d1"]
        assert session.send.call_count == 2

    @mock.patch(SESSION_PATCH)
    def test_client_error_propagates(self, MockSession) -> None:
        # A 403 (bad/insufficient key) must surface at once so get_non_retryable_errors can stop the sync.
        session = MockSession.return_value
        _wire(session, [_resp(status=403, body={"detail": "forbidden"})])

        with pytest.raises(requests.HTTPError):
            _rows(_run("documents", _make_manager()))
        assert session.send.call_count == 1


class TestExecutionEventsFanOut:
    def test_config_is_opt_in_fan_out_with_composite_pk(self) -> None:
        config = VELLUM_ENDPOINTS["workflow_execution_events"]
        assert config.fan_out_over_workflow_deployments is True
        assert config.should_sync_default is False
        assert config.primary_keys == ["workflow_deployment_id", "span_id"]

    @mock.patch(SESSION_PATCH)
    def test_injects_parent_id_into_every_row(self, MockSession) -> None:
        # The parent id completes the composite key; without it rows from different deployments that
        # share a span id would collide and every merge would multi-match.
        session = MockSession.return_value
        _wire(
            session,
            [
                _resp(results=[{"id": "A"}, {"id": "B"}], count=2, url=WFD_URL),
                _resp(results=[{"span_id": "s1", "start": "2026-01-01T00:00:00Z"}], count=1, url=EVENTS_A),
                _resp(results=[{"span_id": "s2", "start": "2026-01-02T00:00:00Z"}], count=1, url=EVENTS_B),
            ],
        )

        rows = _rows(_run("workflow_execution_events", _make_manager()))
        assert rows == [
            {"workflow_deployment_id": "A", "span_id": "s1", "start": "2026-01-01T00:00:00Z"},
            {"workflow_deployment_id": "B", "span_id": "s2", "start": "2026-01-02T00:00:00Z"},
        ]

    @mock.patch(SESSION_PATCH)
    def test_deployment_deleted_mid_fan_out_is_skipped(self, MockSession) -> None:
        # A deployment deleted between enumeration and its fetch 404s — skip it, don't fail the sync.
        session = MockSession.return_value
        _wire(
            session,
            [
                _resp(results=[{"id": "A"}, {"id": "B"}], count=2, url=WFD_URL),
                _resp(status=404, body={"detail": "not found"}, url=EVENTS_A),
                _resp(results=[{"span_id": "s2", "start": "2026-01-02T00:00:00Z"}], count=1, url=EVENTS_B),
            ],
        )

        rows = _rows(_run("workflow_execution_events", _make_manager()))
        assert rows == [{"workflow_deployment_id": "B", "span_id": "s2", "start": "2026-01-02T00:00:00Z"}]

    @mock.patch(SESSION_PATCH)
    def test_non_404_error_propagates(self, MockSession) -> None:
        # Any non-404 child error must fail the whole sync rather than be silently swallowed.
        session = MockSession.return_value
        _wire(
            session,
            [
                _resp(results=[{"id": "A"}], count=1, url=WFD_URL),
                _resp(status=403, body={"detail": "forbidden"}, url=EVENTS_A),
            ],
        )

        with pytest.raises(requests.HTTPError):
            _rows(_run("workflow_execution_events", _make_manager()))

    @mock.patch(SESSION_PATCH)
    def test_resume_skips_completed_deployment(self, MockSession) -> None:
        # Resuming with deployment A already recorded complete must not re-walk A — only B is fetched.
        session = MockSession.return_value
        _wire(
            session,
            [
                _resp(results=[{"id": "A"}, {"id": "B"}], count=2, url=WFD_URL),
                _resp(results=[{"span_id": "s2", "start": "2026-01-02T00:00:00Z"}], count=1, url=EVENTS_B),
            ],
        )

        resume = VellumResumeConfig(
            fanout_state={
                "completed": ["/workflow-deployments/A/execution-events"],
                "current": None,
                "child_state": None,
            }
        )
        rows = _rows(_run("workflow_execution_events", _make_manager(resume)))
        assert rows == [{"workflow_deployment_id": "B", "span_id": "s2", "start": "2026-01-02T00:00:00Z"}]

    @mock.patch(SESSION_PATCH)
    def test_fanout_checkpoint_saved(self, MockSession) -> None:
        # The fan-out must checkpoint its framework resume state so a restart can skip synced parents.
        session = MockSession.return_value
        _wire(
            session,
            [
                _resp(results=[{"id": "A"}], count=1, url=WFD_URL),
                _resp(results=[{"span_id": "s1", "start": "2026-01-01T00:00:00Z"}], count=1, url=EVENTS_A),
            ],
        )

        manager = _make_manager()
        _rows(_run("workflow_execution_events", manager))

        assert manager.save_state.called
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, VellumResumeConfig)
        assert saved.fanout_state is not None
        assert "/workflow-deployments/A/execution-events" in saved.fanout_state["completed"]


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
    @mock.patch(SESSION_PATCH)
    def test_primary_keys_and_partitioning(
        self, endpoint: str, expected_pks: list[str], expected_partition: str | None, MockSession
    ) -> None:
        response = _run(endpoint, _make_manager())
        assert response.primary_keys == expected_pks
        assert response.partition_keys == ([expected_partition] if expected_partition else None)
        assert response.partition_mode == ("datetime" if expected_partition else None)
        assert response.sort_mode == "asc"
