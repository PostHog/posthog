from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane import rocketlane
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.rocketlane import (
    RocketlaneResumeConfig,
    RocketlaneRetryableError,
    check_access,
    get_rows,
    rocketlane_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.settings import (
    ENDPOINTS,
    ROCKETLANE_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = rocketlane._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: RocketlaneResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[RocketlaneResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> RocketlaneResumeConfig | None:
        return self._state

    def save_state(self, data: RocketlaneResumeConfig) -> None:
        self.saved.append(data)


def _page(rows: list[dict], has_more: bool, next_token: str | None) -> dict[str, Any]:
    return {
        "data": rows,
        "pagination": {
            "pageSize": 100,
            "hasMore": has_more,
            "totalRecordCount": len(rows),
            "nextPageToken": next_token,
        },
    }


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str | None, dict],
        endpoint: str = "projects",
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, page_token: str | None, page_size: int, logger: Any) -> dict:
            return pages[page_token]

        monkeypatch.setattr(rocketlane, "_fetch_page", fake_fetch)
        monkeypatch.setattr(rocketlane, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="rl-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_yields_rows_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(
            manager, monkeypatch, {None: _page([{"projectId": 1}, {"projectId": 2}], has_more=False, next_token=None)}
        )
        assert rows == [{"projectId": 1}, {"projectId": 2}]
        # No further pages, so no resume state is persisted.
        assert manager.saved == []

    def test_follows_cursor_until_has_more_is_false(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            None: _page([{"projectId": 1}], has_more=True, next_token="t2"),
            "t2": _page([{"projectId": 2}], has_more=True, next_token="t3"),
            "t3": _page([{"projectId": 3}], has_more=False, next_token=None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"projectId": 1}, {"projectId": 2}, {"projectId": 3}]

    def test_stops_when_next_token_missing_even_if_has_more(self, monkeypatch: Any) -> None:
        # A page advertising hasMore but no token cannot be followed — stop rather than loop.
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: _page([{"projectId": 1}], has_more=True, next_token=None)})
        assert rows == [{"projectId": 1}]
        assert manager.saved == []

    def test_saves_next_token_after_yielding_each_batch(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            None: _page([{"projectId": 1}], has_more=True, next_token="t2"),
            "t2": _page([{"projectId": 2}], has_more=False, next_token=None),
        }
        self._collect(manager, monkeypatch, pages)
        # State is saved AFTER the first page is yielded (pointing at the next token), never for the last.
        assert [s.page_token for s in manager.saved] == ["t2"]

    def test_resumes_from_saved_token(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(RocketlaneResumeConfig(page_token="t2"))
        pages: dict[str | None, dict] = {
            # The first page (token None) must never be fetched on resume.
            "t2": _page([{"projectId": 2}], has_more=True, next_token="t3"),
            "t3": _page([{"projectId": 3}], has_more=False, next_token=None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"projectId": 2}, {"projectId": 3}]

    def test_empty_page_does_not_yield_and_terminates(self, monkeypatch: Any) -> None:
        # An empty page terminates the stream even if the API keeps advertising a cursor.
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: _page([], has_more=True, next_token="t2")})
        assert rows == []
        assert manager.saved == []


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
        with pytest.raises(RocketlaneRetryableError):
            _fetch_page_unwrapped(session, "/projects", None, 100, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/projects", None, 100, MagicMock())

    def test_success_returns_json_body(self) -> None:
        body = _page([{"projectId": 1}], has_more=False, next_token=None)
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "/projects", None, 100, MagicMock())
        assert result == body

    def test_first_request_omits_page_token(self) -> None:
        session = self._session_returning(200, _page([], has_more=False, next_token=None))
        _fetch_page_unwrapped(session, "/projects", None, 100, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"pageSize": 100}

    def test_subsequent_request_includes_page_token(self) -> None:
        session = self._session_returning(200, _page([], has_more=False, next_token=None))
        _fetch_page_unwrapped(session, "/tasks", "abc", 100, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"pageSize": 100, "pageToken": "abc"}


class TestCheckAccess:
    @staticmethod
    def _session_for(response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Rocketlane returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        session = self._session_for(response)
        with patch.object(rocketlane, "make_tracked_session", lambda **kwargs: session):
            assert check_access("rl-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        session = self._session_for(requests.ConnectionError("boom"))
        with patch.object(rocketlane, "make_tracked_session", lambda **kwargs: session):
            status, message = check_access("rl-key")
        assert status == 0
        assert message is not None and "boom" in message


class TestRocketlaneSourceResponse:
    @parameterized.expand(
        [
            ("projects", ["projectId"]),
            ("tasks", ["taskId"]),
            ("time_entries", ["timeEntryId"]),
            ("users", ["userId"]),
            ("fields", ["fieldId"]),
        ]
    )
    def test_response_uses_endpoint_primary_key(self, endpoint: str, primary_keys: list[str]) -> None:
        response = rocketlane_source(
            api_key="rl-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        # Every endpoint exposes a stable `createdAt`, so all partition by datetime.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    def test_endpoint_keys_match_endpoints_tuple(self) -> None:
        assert set(ROCKETLANE_ENDPOINTS) == set(ENDPOINTS)
