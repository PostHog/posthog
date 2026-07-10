from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.vellum import vellum
from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.settings import VELLUM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.vellum import (
    VellumResumeConfig,
    get_rows,
    vellum_source,
)


class _FakeResumableManager:
    def __init__(self, state: VellumResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[VellumResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> VellumResumeConfig | None:
        return self._state

    def save_state(self, data: VellumResumeConfig) -> None:
        self.saved.append(data)


def _response_with_status(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    return response


def _collect(manager: _FakeResumableManager, monkeypatch: Any, endpoint: str, pages: dict) -> list[dict]:
    """Drive get_rows with a fake `_fetch_page` keyed by request URL + offset."""

    def fake_fetch(session: Any, url: str, headers: dict, params: dict, logger: Any) -> dict:
        result = pages[(url, params["offset"])]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(vellum, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for table in get_rows(
        api_key="test-key",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(table.to_pylist())
    return rows


DOCUMENTS_URL = "https://api.vellum.ai/v1/documents"
WFD_URL = "https://api.vellum.ai/v1/workflow-deployments"


class TestOffsetPagination:
    def test_walks_offsets_and_stops_at_count(self, monkeypatch: Any) -> None:
        # offset must advance by the number of rows actually returned, and pagination must stop once
        # the accumulated offset reaches `count` — a wrong terminator either loops forever or truncates.
        pages = {
            (DOCUMENTS_URL, 0): {"count": 3, "results": [{"id": "d1"}, {"id": "d2"}]},
            (DOCUMENTS_URL, 2): {"count": 3, "results": [{"id": "d3"}]},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, "documents", pages)
        assert rows == [{"id": "d1"}, {"id": "d2"}, {"id": "d3"}]

    def test_stops_on_short_page_without_count(self, monkeypatch: Any) -> None:
        # The execution-events response carries no `next`; an empty page is the only stop signal.
        pages = {
            (DOCUMENTS_URL, 0): {"results": [{"id": "d1"}]},
            (DOCUMENTS_URL, 1): {"results": []},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, "documents", pages)
        assert rows == [{"id": "d1"}]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        # A resumed run must skip pages already synced; starting from offset 0 would redo work.
        pages = {(DOCUMENTS_URL, 2): {"count": 3, "results": [{"id": "d3"}]}}
        manager = _FakeResumableManager(VellumResumeConfig(offset=2))
        rows = _collect(manager, monkeypatch, "documents", pages)
        assert rows == [{"id": "d3"}]

    def test_saved_offset_is_current_page_not_next(self, monkeypatch: Any) -> None:
        # Saving the *current* page offset means a crash re-fetches this page and merge dedupes;
        # saving the next page's offset would skip the page's unyielded tail on resume.
        pages = {
            (DOCUMENTS_URL, 0): {"count": 4, "results": [{"id": "d1"}, {"id": "d2"}]},
            (DOCUMENTS_URL, 2): {"count": 4, "results": [{"id": "d3"}, {"id": "d4"}]},
        }
        manager = _FakeResumableManager()

        def fake_fetch(session: Any, url: str, headers: dict, params: dict, logger: Any) -> dict:
            return pages[(url, params["offset"])]

        monkeypatch.setattr(vellum, "_fetch_page", fake_fetch)
        # chunk_size=1 forces a yield (and a save) after every row.
        batcher = Batcher(logger=MagicMock(), chunk_size=1, chunk_size_bytes=100 * 1024 * 1024)
        list(
            vellum._paginate(
                MagicMock(),
                DOCUMENTS_URL,
                {},
                MagicMock(),
                batcher,
                manager,  # type: ignore[arg-type]
                ordering=None,
                start_offset=0,
                deployment_id=None,
            )
        )
        # Rows from page-1 save offset 0, rows from page-2 save offset 2 — never 2 while still on page 1.
        assert [s.offset for s in manager.saved] == [0, 0, 2, 2]

    def test_ordering_param_sent_when_configured(self, monkeypatch: Any) -> None:
        # workflow_deployments paginates oldest-first via ?ordering=created for a stable page order;
        # dropping it risks page-boundary skips/dupes as rows are inserted mid-sync.
        seen: list[dict] = []

        def fake_fetch(session: Any, url: str, headers: dict, params: dict, logger: Any) -> dict:
            seen.append(params)
            return {"count": 0, "results": []}

        monkeypatch.setattr(vellum, "_fetch_page", fake_fetch)
        list(get_rows("k", "workflow_deployments", MagicMock(), _FakeResumableManager()))  # type: ignore[arg-type]
        assert seen[0]["ordering"] == "created"
        # documents has no stable created field, so no ordering is forced.
        seen.clear()
        list(get_rows("k", "documents", MagicMock(), _FakeResumableManager()))  # type: ignore[arg-type]
        assert "ordering" not in seen[0]


EVENTS_A = "https://api.vellum.ai/v1/workflow-deployments/A/execution-events"
EVENTS_B = "https://api.vellum.ai/v1/workflow-deployments/B/execution-events"


class TestExecutionEventsFanOut:
    def test_config_is_opt_in_fan_out_with_composite_pk(self) -> None:
        config = VELLUM_ENDPOINTS["workflow_execution_events"]
        assert config.fan_out_over_workflow_deployments is True
        assert config.should_sync_default is False
        assert config.primary_keys == ["workflow_deployment_id", "span_id"]

    def test_injects_parent_id_into_every_row(self, monkeypatch: Any) -> None:
        # The parent id completes the composite key; without it rows from different deployments that
        # share a span id would collide and every merge would multi-match (the OOM failure mode).
        pages = {
            (WFD_URL, 0): {"count": 2, "results": [{"id": "A"}, {"id": "B"}]},
            (EVENTS_A, 0): {"count": 1, "results": [{"span_id": "s1", "start": "2026-01-01T00:00:00Z"}]},
            (EVENTS_B, 0): {"count": 1, "results": [{"span_id": "s2", "start": "2026-01-02T00:00:00Z"}]},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, "workflow_execution_events", pages)
        assert rows == [
            {"workflow_deployment_id": "A", "span_id": "s1", "start": "2026-01-01T00:00:00Z"},
            {"workflow_deployment_id": "B", "span_id": "s2", "start": "2026-01-02T00:00:00Z"},
        ]

    def test_deployment_deleted_mid_fan_out_is_skipped(self, monkeypatch: Any) -> None:
        not_found = requests.HTTPError(response=_response_with_status(404))
        pages = {
            (WFD_URL, 0): {"count": 2, "results": [{"id": "A"}, {"id": "B"}]},
            (EVENTS_A, 0): not_found,
            (EVENTS_B, 0): {"count": 1, "results": [{"span_id": "s2", "start": "2026-01-02T00:00:00Z"}]},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, "workflow_execution_events", pages)
        assert rows == [{"workflow_deployment_id": "B", "span_id": "s2", "start": "2026-01-02T00:00:00Z"}]

    def test_non_404_error_propagates(self, monkeypatch: Any) -> None:
        server_error = requests.HTTPError(response=_response_with_status(500))
        pages = {
            (WFD_URL, 0): {"count": 1, "results": [{"id": "A"}]},
            (EVENTS_A, 0): server_error,
        }
        with pytest.raises(requests.HTTPError):
            _collect(_FakeResumableManager(), monkeypatch, "workflow_execution_events", pages)

    def test_resume_from_bookmarked_deployment(self, monkeypatch: Any) -> None:
        # Resuming must restart at the bookmarked deployment (B), not re-walk A from the top.
        pages = {
            (WFD_URL, 0): {"count": 2, "results": [{"id": "A"}, {"id": "B"}]},
            (EVENTS_B, 0): {"count": 1, "results": [{"span_id": "s2", "start": "2026-01-02T00:00:00Z"}]},
        }
        manager = _FakeResumableManager(VellumResumeConfig(offset=0, deployment_id="B"))
        rows = _collect(manager, monkeypatch, "workflow_execution_events", pages)
        assert rows == [{"workflow_deployment_id": "B", "span_id": "s2", "start": "2026-01-02T00:00:00Z"}]


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("chunked_encoding", requests.exceptions.ChunkedEncodingError("Connection broken")),
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
        ]
    )
    def test_transient_errors_are_retried(self, _name: str, transient_error: Exception) -> None:
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"count": 0, "results": []}
        session = MagicMock()
        session.get.side_effect = [transient_error, good]

        with patch.object(vellum._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = vellum._fetch_page(session, WFD_URL, {}, {"offset": 0}, MagicMock())

        assert result == {"count": 0, "results": []}
        assert session.get.call_count == 2

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_retry(self, _name: str, status_code: int) -> None:
        bad = MagicMock(status_code=status_code)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"count": 0, "results": []}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(vellum._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = vellum._fetch_page(session, WFD_URL, {}, {"offset": 0}, MagicMock())

        assert result == {"count": 0, "results": []}
        assert session.get.call_count == 2

    def test_client_error_raises_immediately(self) -> None:
        # A 403 (bad/insufficient key) must surface at once so get_non_retryable_errors can stop the sync.
        bad = MagicMock(status_code=403, ok=False, text="Invalid API key")
        bad.raise_for_status.side_effect = requests.HTTPError("403 Client Error: Forbidden", response=bad)
        session = MagicMock()
        session.get.return_value = bad

        with pytest.raises(requests.HTTPError):
            vellum._fetch_page(session, WFD_URL, {}, {"offset": 0}, MagicMock())
        assert session.get.call_count == 1


class TestSourceResponse:
    @parameterized.expand(
        [
            ("workflow_deployments", ["id"], "created"),
            ("prompt_deployments", ["id"], "created"),
            ("document_indexes", ["id"], "created"),
            # documents exposes only the mutable last_uploaded_at, so it must not be partitioned.
            ("documents", ["id"], None),
            ("workflow_execution_events", ["workflow_deployment_id", "span_id"], "start"),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, expected_pks: list[str], expected_partition: str | None
    ) -> None:
        response = vellum_source("k", endpoint, MagicMock(), MagicMock())
        assert response.primary_keys == expected_pks
        assert response.partition_keys == ([expected_partition] if expected_partition else None)
        assert response.partition_mode == ("datetime" if expected_partition else None)
        assert response.sort_mode == "asc"
