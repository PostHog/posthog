from typing import Any, Optional

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.tavus import tavus
from products.warehouse_sources.backend.temporal.data_imports.sources.tavus.settings import ENDPOINTS, TAVUS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tavus.tavus import (
    TavusResumeConfig,
    TavusRetryableError,
    check_access,
    get_rows,
    tavus_source,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = tavus._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: TavusResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[TavusResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> TavusResumeConfig | None:
        return self._state

    def save_state(self, data: TavusResumeConfig) -> None:
        self.saved.append(data)


def _page(items: list[dict], total_count: Optional[int] = None) -> dict[str, Any]:
    return {"data": items, "total_count": total_count if total_count is not None else len(items)}


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[int, dict],
        endpoint: str = "videos",
        page_size: int = 2,
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, page: int, limit: int, logger: Any) -> dict:
            return pages[page]

        # Shrink the page size so small fixtures exercise multi-page pagination and short-page termination.
        monkeypatch.setattr(tavus, "PAGE_SIZE", page_size)
        monkeypatch.setattr(tavus, "_fetch_page", fake_fetch)
        monkeypatch.setattr(tavus, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="tavus-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_short_page_yields_items_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: _page([{"video_id": "a"}], total_count=1)})
        assert rows == [{"video_id": "a"}]
        # A short page ends the sync, so no resume state is persisted.
        assert manager.saved == []

    def test_follows_pagination_until_short_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            0: _page([{"video_id": "a"}, {"video_id": "b"}], total_count=5),
            1: _page([{"video_id": "c"}, {"video_id": "d"}], total_count=5),
            2: _page([{"video_id": "e"}], total_count=5),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert [r["video_id"] for r in rows] == ["a", "b", "c", "d", "e"]

    def test_stops_when_running_count_reaches_total(self, monkeypatch: Any) -> None:
        # Final page is full (== PAGE_SIZE), so termination relies on total_count, not a short page.
        manager = _FakeResumableManager()
        pages = {
            0: _page([{"video_id": "a"}, {"video_id": "b"}], total_count=4),
            1: _page([{"video_id": "c"}, {"video_id": "d"}], total_count=4),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert [r["video_id"] for r in rows] == ["a", "b", "c", "d"]
        # Page 2 must never be requested; state is only saved once (after page 0).
        assert [s.next_page for s in manager.saved] == [1]

    def test_saves_next_page_after_yielding_each_batch(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            0: _page([{"video_id": "a"}, {"video_id": "b"}], total_count=3),
            1: _page([{"video_id": "c"}], total_count=3),
        }
        self._collect(manager, monkeypatch, pages)
        # State is saved AFTER page 0 is yielded (pointing at page 1), and never for the final page.
        assert [s.next_page for s in manager.saved] == [1]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(TavusResumeConfig(next_page=1))
        pages = {
            # Page 0 must never be fetched on resume.
            1: _page([{"video_id": "c"}, {"video_id": "d"}], total_count=3),
            2: _page([{"video_id": "e"}], total_count=3),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert [r["video_id"] for r in rows] == ["c", "d", "e"]

    def test_empty_data_does_not_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: _page([], total_count=0)})
        assert rows == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: dict | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body or {}
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(TavusRetryableError):
            _fetch_page_unwrapped(session, "/videos", 0, 100, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/videos", 0, 100, MagicMock())

    def test_success_returns_json_body(self) -> None:
        body = _page([{"video_id": "a"}], total_count=1)
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "/videos", 0, 100, MagicMock())
        assert result == body

    def test_request_uses_page_and_limit_params(self) -> None:
        session = self._session_returning(200, _page([], total_count=0))
        _fetch_page_unwrapped(session, "/replicas", 3, 100, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"page": 3, "limit": 100}


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(tavus, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Tavus returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("tavus-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("tavus-key")
        assert status == 0
        assert message is not None and "boom" in message


class TestTavusSourceResponse:
    @parameterized.expand(
        [
            ("videos", "video_id"),
            ("replicas", "replica_id"),
            ("personas", "persona_id"),
            ("conversations", "conversation_id"),
        ]
    )
    def test_primary_key_matches_endpoint_config(self, endpoint: str, primary_key: str) -> None:
        response = tavus_source(
            api_key="tavus-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == [primary_key]
        # No endpoint exposes a curl-verified creation field, so none partition.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_a_resource_specific_primary_key(self) -> None:
        assert {name: cfg.primary_keys for name, cfg in TAVUS_ENDPOINTS.items()} == {
            "videos": ["video_id"],
            "replicas": ["replica_id"],
            "personas": ["persona_id"],
            "conversations": ["conversation_id"],
        }
        assert set(TAVUS_ENDPOINTS) == set(ENDPOINTS)
