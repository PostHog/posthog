from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach import smartreach
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.settings import (
    ENDPOINTS,
    SMARTREACH_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.smartreach import (
    SmartreachResumeConfig,
    SmartreachRetryableError,
    check_access,
    get_rows,
    smartreach_source,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = smartreach._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: SmartreachResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SmartreachResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SmartreachResumeConfig | None:
        return self._state

    def save_state(self, data: SmartreachResumeConfig) -> None:
        self.saved.append(data)


def _page(rows: list[dict], data_key: str, next_url: str | None) -> dict[str, Any]:
    return {"data": {data_key: rows}, "links": {"next": next_url}}


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages_by_url: dict[str, dict],
        endpoint: str = "prospects",
    ) -> tuple[list[dict], list[str]]:
        fetched_urls: list[str] = []

        def fake_fetch(session: Any, url: str, logger: Any) -> dict:
            fetched_urls.append(url)
            return pages_by_url[url]

        monkeypatch.setattr(smartreach, "_fetch_page", fake_fetch)
        monkeypatch.setattr(smartreach, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="uk_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows, fetched_urls

    def test_single_page_yields_rows_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        start = "https://api.smartreach.io/api/v1/prospects"
        rows, urls = self._collect(
            manager, monkeypatch, {start: _page([{"id": 1}, {"id": 2}], "prospects", next_url=None)}
        )
        assert rows == [{"id": 1}, {"id": 2}]
        assert urls == [start]
        # No further pages, so no resume state is persisted.
        assert manager.saved == []

    def test_follows_links_next_until_null(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        start = "https://api.smartreach.io/api/v1/prospects"
        p2 = "https://api.smartreach.io/api/v1/prospects?cursor=abc"
        p3 = "https://api.smartreach.io/api/v1/prospects?cursor=def"
        pages = {
            start: _page([{"id": 1}], "prospects", next_url=p2),
            p2: _page([{"id": 2}], "prospects", next_url=p3),
            p3: _page([{"id": 3}], "prospects", next_url=None),
        }
        rows, urls = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        # The follow-up requests hit the verbatim links.next URLs.
        assert urls == [start, p2, p3]

    def test_saves_next_url_after_yielding_each_batch(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        start = "https://api.smartreach.io/api/v1/prospects"
        p2 = "https://api.smartreach.io/api/v1/prospects?cursor=abc"
        pages = {
            start: _page([{"id": 1}], "prospects", next_url=p2),
            p2: _page([{"id": 2}], "prospects", next_url=None),
        }
        self._collect(manager, monkeypatch, pages)
        # State is saved AFTER page 1 is yielded (pointing at the next URL), never for the final page.
        assert [s.next_url for s in manager.saved] == [p2]

    def test_resumes_from_saved_cursor_url(self, monkeypatch: Any) -> None:
        p2 = "https://api.smartreach.io/api/v1/prospects?cursor=abc"
        p3 = "https://api.smartreach.io/api/v1/prospects?cursor=def"
        manager = _FakeResumableManager(SmartreachResumeConfig(next_url=p2))
        pages = {
            # The first-page URL must never be fetched on resume.
            p2: _page([{"id": 2}], "prospects", next_url=p3),
            p3: _page([{"id": 3}], "prospects", next_url=None),
        }
        rows, urls = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 2}, {"id": 3}]
        assert urls == [p2, p3]

    def test_empty_page_does_not_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        start = "https://api.smartreach.io/api/v1/prospects"
        rows, _urls = self._collect(manager, monkeypatch, {start: _page([], "prospects", next_url=None)})
        assert rows == []

    def test_reads_rows_from_endpoint_specific_data_key(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        start = "https://api.smartreach.io/api/v1/campaigns"
        rows, _urls = self._collect(
            manager,
            monkeypatch,
            {start: _page([{"id": 9}], "campaigns", next_url=None)},
            endpoint="campaigns",
        )
        assert rows == [{"id": 9}]


class TestExtractRows:
    def test_reads_nested_data_key(self) -> None:
        data = {"data": {"prospects": [{"id": 1}]}}
        assert smartreach._extract_rows(data, "prospects") == [{"id": 1}]

    def test_tolerates_bare_data_list(self) -> None:
        data = {"data": [{"id": 1}]}
        assert smartreach._extract_rows(data, "prospects") == [{"id": 1}]

    @parameterized.expand([("missing_data", {}), ("null_data", {"data": None}), ("wrong_key", {"data": {"other": []}})])
    def test_returns_empty_when_rows_absent(self, _name: str, data: dict[str, Any]) -> None:
        assert smartreach._extract_rows(data, "prospects") == []


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
        with pytest.raises(SmartreachRetryableError):
            _fetch_page_unwrapped(session, "https://api.smartreach.io/api/v1/prospects", MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "https://api.smartreach.io/api/v1/prospects", MagicMock())

    def test_success_returns_json_body(self) -> None:
        body = _page([{"id": 1}], "prospects", next_url=None)
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "https://api.smartreach.io/api/v1/prospects", MagicMock())
        assert result == body

    def test_follows_next_url_verbatim_without_extra_params(self) -> None:
        # A links.next URL already carries its pagination params; the fetch must not add its own.
        session = self._session_returning(200, _page([], "prospects", next_url=None))
        next_url = "https://api.smartreach.io/api/v1/prospects?cursor=abc"
        _fetch_page_unwrapped(session, next_url, MagicMock())
        args, kwargs = session.get.call_args
        assert args[0] == next_url
        assert "params" not in kwargs


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(smartreach, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "SmartReach returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("uk_test") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("uk_test")
        assert status == 0
        assert message is not None and "boom" in message


class TestSmartreachSourceResponse:
    @parameterized.expand([("prospects",), ("campaigns",)])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = smartreach_source(
            api_key="uk_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Full refresh only: no datetime partitioning is configured.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SMARTREACH_ENDPOINTS.values())
        assert set(SMARTREACH_ENDPOINTS) == set(ENDPOINTS)
