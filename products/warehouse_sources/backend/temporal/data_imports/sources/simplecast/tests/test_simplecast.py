from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.simplecast import simplecast
from products.warehouse_sources.backend.temporal.data_imports.sources.simplecast.settings import (
    ENDPOINTS,
    SIMPLECAST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.simplecast.simplecast import (
    PAGE_SIZE,
    SimpleCastResumeConfig,
    SimpleCastRetryableError,
    check_access,
    get_rows,
    simplecast_source,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = simplecast._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: SimpleCastResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SimpleCastResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SimpleCastResumeConfig | None:
        return self._state

    def save_state(self, data: SimpleCastResumeConfig) -> None:
        self.saved.append(data)


def _full_page(start_id: int) -> list[dict]:
    return [{"id": start_id + i} for i in range(PAGE_SIZE)]


def _envelope(items: list[dict], total: int, current: int) -> dict:
    return {"collection": items, "pages": {"total": total, "current": current}}


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[int, tuple[list[dict], bool]],
        endpoint: str = "podcasts",
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, offset: int, limit: int, logger: Any) -> tuple[list[dict], bool]:
            return pages[offset]

        monkeypatch.setattr(simplecast, "_fetch_page", fake_fetch)
        monkeypatch.setattr(simplecast, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="sc-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_short_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: ([{"id": 1}, {"id": 2}], False)})
        assert rows == [{"id": 1}, {"id": 2}]
        # The page is short (< PAGE_SIZE), so we stop without persisting resume state.
        assert manager.saved == []

    def test_stops_on_last_page_flag_even_when_full(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        # A full page that the paging metadata marks as the last one must terminate the loop.
        rows = self._collect(manager, monkeypatch, {0: (_full_page(0), True)})
        assert len(rows) == PAGE_SIZE
        assert manager.saved == []

    def test_follows_offset_pagination_until_short_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {0: (_full_page(0), False), PAGE_SIZE: ([{"id": 999}], False)}
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1
        # State is saved after the first full page (offset advances to PAGE_SIZE), then we stop.
        assert [s.offset for s in manager.saved] == [PAGE_SIZE]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SimpleCastResumeConfig(offset=PAGE_SIZE))
        # Offset 0 must never be fetched on resume.
        pages = {PAGE_SIZE: ([{"id": 5}], False)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 5}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: ([], False)})
        assert rows == []
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else _envelope([], total=1, current=1)
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
        with pytest.raises(SimpleCastRetryableError):
            _fetch_page_unwrapped(session, "/podcasts", 0, PAGE_SIZE, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/podcasts", 0, PAGE_SIZE, MagicMock())

    def test_success_returns_collection_and_not_last(self) -> None:
        body = _envelope([{"id": 1}], total=3, current=1)
        session = self._session_returning(200, body)
        items, is_last = _fetch_page_unwrapped(session, "/podcasts", 0, PAGE_SIZE, MagicMock())
        assert items == [{"id": 1}]
        assert is_last is False

    def test_success_marks_last_page_when_current_reaches_total(self) -> None:
        body = _envelope([{"id": 1}], total=2, current=2)
        session = self._session_returning(200, body)
        items, is_last = _fetch_page_unwrapped(session, "/podcasts", 0, PAGE_SIZE, MagicMock())
        assert items == [{"id": 1}]
        assert is_last is True

    @parameterized.expand(
        [("bare_list", [{"id": 1}]), ("missing_collection", {"pages": {}}), ("error", {"error": "no"})]
    )
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(SimpleCastRetryableError):
            _fetch_page_unwrapped(session, "/podcasts", 0, PAGE_SIZE, MagicMock())

    def test_request_uses_limit_and_offset_params(self) -> None:
        session = self._session_returning(200, _envelope([], total=1, current=1))
        _fetch_page_unwrapped(session, "/podcasts", 200, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE, "offset": 200}


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(simplecast, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Simplecast returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("sc-token") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("sc-token")
        assert status == 0
        assert message is not None and "boom" in message

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Simplecast API token"),
            (403, False, "Invalid Simplecast API token"),
            (500, False, "Simplecast returned HTTP 500"),
        ],
    )
    def test_validate_credentials(
        self, status: int, expected_valid: bool, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._patch_session(monkeypatch, response)
        assert validate_credentials("sc-token") == (expected_valid, expected_message)


class TestSimpleCastSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = simplecast_source(
            api_key="sc-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SIMPLECAST_ENDPOINTS.values())
        assert set(SIMPLECAST_ENDPOINTS) == set(ENDPOINTS)
