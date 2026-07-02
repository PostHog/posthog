from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai import devin_ai
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.devin_ai import (
    DEVIN_AI_BASE_URL,
    PAGE_SIZE,
    DevinAIResumeConfig,
    _endpoint_path,
    devin_ai_source,
    get_rows,
    get_status_code,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.settings import DEVIN_AI_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: DevinAIResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[DevinAIResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> DevinAIResumeConfig | None:
        return self._state

    def save_state(self, data: DevinAIResumeConfig) -> None:
        self.saved.append(data)


def _collect(manager: _FakeResumableManager, monkeypatch: Any, endpoint: str, pages: list[dict]) -> list[dict]:
    """Feed successive `pages` from _fetch_page and return the flattened rows."""
    calls: list[dict[str, Any]] = []

    def fake_fetch(session: Any, url: str, params: dict[str, Any], headers: dict[str, str], logger: Any) -> dict:
        calls.append({"url": url, "params": params})
        return pages[len(calls) - 1]

    monkeypatch.setattr(devin_ai, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for page in get_rows(
        api_key="cog_test",
        org_id="org-abc",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        # get_rows yields one page's items as a list[dict]; the pipeline batches internally.
        rows.extend(page)
    manager.calls = calls  # type: ignore[attr-defined]
    return rows


class TestEndpointPath:
    @parameterized.expand(
        [
            ("sessions", "/v3/organizations/org-abc/sessions"),
            ("playbooks", "/v3/organizations/org-abc/playbooks"),
            ("knowledge_notes", "/v3/organizations/org-abc/knowledge/notes"),
            ("secrets", "/v3/organizations/org-abc/secrets"),
        ]
    )
    def test_org_id_is_interpolated_into_path(self, endpoint: str, expected: str) -> None:
        assert _endpoint_path(endpoint, "org-abc") == expected

    @parameterized.expand(
        [
            ("path_traversal", "org-abc/../billing"),
            ("query_injection", "org-abc?first=1"),
            ("slash", "org/abc"),
            ("empty", ""),
            ("whitespace_only", "   "),
        ]
    )
    def test_malicious_org_id_is_rejected(self, _name: str, org_id: str) -> None:
        # A malformed org_id must not be able to inject `/` or `?` to route the stored key elsewhere.
        with pytest.raises(ValueError):
            _endpoint_path("sessions", org_id)


class TestGetRows:
    def test_yields_items_as_dicts(self, monkeypatch: Any) -> None:
        pages = [{"items": [{"session_id": "s1"}, {"session_id": "s2"}], "has_next_page": False, "end_cursor": None}]
        rows = _collect(_FakeResumableManager(), monkeypatch, "sessions", pages)
        assert rows == [{"session_id": "s1"}, {"session_id": "s2"}]

    def test_first_page_has_no_after_and_uses_page_size(self, monkeypatch: Any) -> None:
        pages = [{"items": [{"session_id": "s1"}], "has_next_page": False, "end_cursor": None}]
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, "sessions", pages)
        first_call = manager.calls[0]  # type: ignore[attr-defined]
        assert first_call["params"] == {"first": PAGE_SIZE}

    def test_follows_cursor_pagination(self, monkeypatch: Any) -> None:
        pages = [
            {"items": [{"session_id": "s1"}], "has_next_page": True, "end_cursor": "cur1"},
            {"items": [{"session_id": "s2"}], "has_next_page": False, "end_cursor": None},
        ]
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, "sessions", pages)
        assert rows == [{"session_id": "s1"}, {"session_id": "s2"}]
        # Second request must carry the cursor from the first page's end_cursor.
        assert manager.calls[1]["params"] == {"first": PAGE_SIZE, "after": "cur1"}  # type: ignore[attr-defined]

    def test_stops_when_has_next_page_false_even_if_cursor_present(self, monkeypatch: Any) -> None:
        # A defensive guard: if the API returns a cursor but has_next_page is false, we must not loop.
        pages = [{"items": [{"session_id": "s1"}], "has_next_page": False, "end_cursor": "cur1"}]
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, "sessions", pages)
        assert rows == [{"session_id": "s1"}]
        assert len(manager.calls) == 1  # type: ignore[attr-defined]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        pages = [{"items": [{"session_id": "s3"}], "has_next_page": False, "end_cursor": None}]
        manager = _FakeResumableManager(DevinAIResumeConfig(after="saved_cursor"))
        rows = _collect(manager, monkeypatch, "sessions", pages)
        assert rows == [{"session_id": "s3"}]
        assert manager.calls[0]["params"] == {"first": PAGE_SIZE, "after": "saved_cursor"}  # type: ignore[attr-defined]

    def test_saves_next_cursor_at_page_boundary_only(self, monkeypatch: Any) -> None:
        # State is saved once per completed page that has a successor, after the page is yielded — so a
        # crash re-fetches the last page (merge dedupes) rather than skipping its tail.
        pages = [
            {"items": [{"session_id": "s1"}], "has_next_page": True, "end_cursor": "cur1"},
            {"items": [{"session_id": "s2"}], "has_next_page": True, "end_cursor": "cur2"},
            {"items": [{"session_id": "s3"}], "has_next_page": False, "end_cursor": None},
        ]
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, "sessions", pages)
        # No save after the final page (nothing left to resume into).
        assert manager.saved == [DevinAIResumeConfig(after="cur1"), DevinAIResumeConfig(after="cur2")]


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("rate_limited", 429),
            ("server_error", 500),
            ("bad_gateway", 502),
        ]
    )
    def test_retryable_status_codes_are_retried(self, _name: str, status_code: int) -> None:
        retryable = MagicMock()
        retryable.status_code = status_code
        retryable.ok = False

        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"items": []}

        session = MagicMock()
        session.get.side_effect = [retryable, good]

        with patch.object(devin_ai._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = devin_ai._fetch_page(session, f"{DEVIN_AI_BASE_URL}/x", {}, {}, MagicMock())

        assert result == {"items": []}
        assert session.get.call_count == 2

    @parameterized.expand(
        [
            ("chunked_encoding", requests.exceptions.ChunkedEncodingError("Connection broken")),
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
        ]
    )
    def test_transient_transport_errors_are_retried(self, _name: str, transient_error: Exception) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"items": []}

        session = MagicMock()
        session.get.side_effect = [transient_error, good]

        with patch.object(devin_ai._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = devin_ai._fetch_page(session, f"{DEVIN_AI_BASE_URL}/x", {}, {}, MagicMock())

        assert result == {"items": []}
        assert session.get.call_count == 2

    def test_client_error_raises_immediately(self) -> None:
        forbidden = MagicMock()
        forbidden.status_code = 403
        forbidden.ok = False
        forbidden.raise_for_status.side_effect = requests.HTTPError("403 Client Error", response=forbidden)

        session = MagicMock()
        session.get.return_value = forbidden

        with pytest.raises(requests.HTTPError):
            devin_ai._fetch_page(session, f"{DEVIN_AI_BASE_URL}/x", {}, {}, MagicMock())

        assert session.get.call_count == 1


class TestGetStatusCode:
    def test_returns_status_and_probes_with_first_one(self) -> None:
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response

        with patch.object(devin_ai, "make_tracked_session", return_value=session):
            status = get_status_code("cog_test", "org-abc", "sessions")

        assert status == 200
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"first": 1}
        assert kwargs["headers"]["Authorization"] == "Bearer cog_test"


class TestDevinAISource:
    @parameterized.expand(list(DEVIN_AI_ENDPOINTS.keys()))
    def test_source_response_uses_endpoint_primary_keys_and_stable_partition(self, endpoint: str) -> None:
        response = devin_ai_source(
            api_key="cog_test",
            org_id="org-abc",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        cfg = DEVIN_AI_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        # created_at is a stable field — never updated_at — so partitions don't rewrite each sync.
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
