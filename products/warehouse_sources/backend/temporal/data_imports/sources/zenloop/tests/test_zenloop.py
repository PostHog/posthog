from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop import zenloop
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.settings import (
    ENDPOINTS,
    ZENLOOP_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.zenloop import (
    ZenloopResumeConfig,
    ZenloopRetryableError,
    check_access,
    get_rows,
    zenloop_source,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = zenloop._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: ZenloopResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ZenloopResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ZenloopResumeConfig | None:
        return self._state

    def save_state(self, data: ZenloopResumeConfig) -> None:
        self.saved.append(data)


def _page(items: list[dict], response_key: str = "surveys") -> dict[str, Any]:
    # The row list lives under a named key alongside a `meta` block in the real envelope.
    return {response_key: items, "meta": {"per_page": zenloop.PER_PAGE}}


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager, monkeypatch: Any, pages: dict[int, dict], endpoint: str = "surveys"
    ) -> list[dict]:
        # Shrink the page size so a page of 2 rows counts as "full" and a shorter page terminates.
        monkeypatch.setattr(zenloop, "PER_PAGE", 2)

        def fake_fetch(session: Any, path: str, page: int, per_page: int, logger: Any) -> dict:
            return pages[page]

        monkeypatch.setattr(zenloop, "_fetch_page", fake_fetch)
        monkeypatch.setattr(zenloop, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_token="zenloop-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_short_page_yields_items_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page([{"id": 1}])})
        assert rows == [{"id": 1}]
        # Page shorter than PER_PAGE, so no resume state is persisted.
        assert manager.saved == []

    def test_follows_pagination_until_short_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            1: _page([{"id": 1}, {"id": 2}]),
            2: _page([{"id": 3}, {"id": 4}]),
            3: _page([{"id": 5}]),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]

    def test_saves_next_page_after_yielding_each_full_batch(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            1: _page([{"id": 1}, {"id": 2}]),
            2: _page([{"id": 3}]),
        }
        self._collect(manager, monkeypatch, pages)
        # State is saved AFTER the full page 1 is yielded (pointing at page 2), never for the final short page.
        assert [s.next_page for s in manager.saved] == [2]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(ZenloopResumeConfig(next_page=2))
        pages = {
            # Page 1 must never be fetched on resume.
            2: _page([{"id": 3}, {"id": 4}]),
            3: _page([{"id": 5}]),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 3}, {"id": 4}, {"id": 5}]

    def test_empty_page_does_not_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page([])})
        assert rows == []

    def test_selects_rows_under_endpoint_named_key(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {1: _page([{"id": 9}], response_key="properties")}
        rows = self._collect(manager, monkeypatch, pages, endpoint="properties")
        assert rows == [{"id": 9}]


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
        with pytest.raises(ZenloopRetryableError):
            _fetch_page_unwrapped(session, "/surveys", 1, 50, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/surveys", 1, 50, MagicMock())

    def test_success_returns_json_body(self) -> None:
        body = _page([{"id": 1}])
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "/surveys", 1, 50, MagicMock())
        assert result == body

    def test_request_uses_page_and_per_page_params(self) -> None:
        session = self._session_returning(200, _page([]))
        _fetch_page_unwrapped(session, "/properties", 3, 50, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"page": 3, "per_page": 50}


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(zenloop, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Zenloop returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("zenloop-token") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("zenloop-token")
        assert status == 0
        assert message is not None and "boom" in message


class TestZenloopSourceResponse:
    @parameterized.expand([("surveys",), ("survey_groups",), ("properties",)])
    def test_response_shape_matches_endpoint_config(self, endpoint: str) -> None:
        response = zenloop_source(
            api_token="zenloop-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No endpoint exposes a creation-timestamp partition key, so partitioning stays off.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in ZENLOOP_ENDPOINTS.values())
        assert set(ZENLOOP_ENDPOINTS) == set(ENDPOINTS)
