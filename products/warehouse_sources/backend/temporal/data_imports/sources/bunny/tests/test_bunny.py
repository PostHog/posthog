from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bunny import bunny
from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.bunny import (
    BunnyResumeConfig,
    BunnyRetryableError,
    bunny_source,
    check_access,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.settings import BUNNY_ENDPOINTS, ENDPOINTS

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = bunny._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: BunnyResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[BunnyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> BunnyResumeConfig | None:
        return self._state

    def save_state(self, data: BunnyResumeConfig) -> None:
        self.saved.append(data)


def _page(items: list[dict], has_more: bool) -> dict[str, Any]:
    return {"Items": items, "CurrentPage": 1, "TotalItems": len(items), "HasMoreItems": has_more}


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager, monkeypatch: Any, pages: dict[int, dict], endpoint: str = "pull_zones"
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, page: int, per_page: int, logger: Any) -> dict:
            return pages[page]

        monkeypatch.setattr(bunny, "_fetch_page", fake_fetch)
        monkeypatch.setattr(bunny, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            access_key="bunny-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_yields_items_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page([{"Id": 1}, {"Id": 2}], has_more=False)})
        assert rows == [{"Id": 1}, {"Id": 2}]
        # No further pages, so no resume state is persisted.
        assert manager.saved == []

    def test_follows_pagination_until_has_more_is_false(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            1: _page([{"Id": 1}], has_more=True),
            2: _page([{"Id": 2}], has_more=True),
            3: _page([{"Id": 3}], has_more=False),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"Id": 1}, {"Id": 2}, {"Id": 3}]

    def test_saves_next_page_after_yielding_each_batch(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            1: _page([{"Id": 1}], has_more=True),
            2: _page([{"Id": 2}], has_more=False),
        }
        self._collect(manager, monkeypatch, pages)
        # State is saved AFTER page 1 is yielded (pointing at page 2), and never for the final page.
        assert [s.next_page for s in manager.saved] == [2]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(BunnyResumeConfig(next_page=2))
        pages = {
            # Page 1 must never be fetched on resume.
            2: _page([{"Id": 2}], has_more=True),
            3: _page([{"Id": 3}], has_more=False),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"Id": 2}, {"Id": 3}]

    def test_empty_items_does_not_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page([], has_more=False)})
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
        with pytest.raises(BunnyRetryableError):
            _fetch_page_unwrapped(session, "/pullzone", 1, 1000, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/pullzone", 1, 1000, MagicMock())

    def test_success_returns_json_body(self) -> None:
        body = _page([{"Id": 1}], has_more=False)
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "/pullzone", 1, 1000, MagicMock())
        assert result == body

    def test_request_uses_page_and_per_page_params(self) -> None:
        session = self._session_returning(200, _page([], has_more=False))
        _fetch_page_unwrapped(session, "/dnszone", 3, 1000, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"page": 3, "perPage": 1000}


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(bunny, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "bunny.net returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("bunny-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("bunny-key")
        assert status == 0
        assert message is not None and "boom" in message


class TestBunnySourceResponse:
    @parameterized.expand(
        [
            ("pull_zones", None),
            ("storage_zones", None),
            ("dns_zones", "DateCreated"),
            ("video_libraries", "DateCreated"),
        ]
    )
    def test_partitioning_matches_endpoint_config(self, endpoint: str, partition_key: str | None) -> None:
        response = bunny_source(
            access_key="bunny-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["Id"]
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        # bunny.net IDs are globally unique, so a single `Id` key is sufficient table-wide.
        assert all(config.primary_keys == ["Id"] for config in BUNNY_ENDPOINTS.values())
        assert set(BUNNY_ENDPOINTS) == set(ENDPOINTS)
