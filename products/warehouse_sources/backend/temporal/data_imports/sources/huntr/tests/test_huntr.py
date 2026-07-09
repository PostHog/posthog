from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.huntr import huntr
from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.huntr import (
    PAGE_SIZE,
    HuntrResumeConfig,
    HuntrRetryableError,
    check_access,
    get_rows,
    huntr_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.settings import ENDPOINTS, HUNTR_ENDPOINTS

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = huntr._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: HuntrResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[HuntrResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> HuntrResumeConfig | None:
        return self._state

    def save_state(self, data: HuntrResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str | None, tuple[list[dict], str | None]],
        endpoint: str = "members",
    ) -> list[dict]:
        def fake_fetch(
            session: Any, path: str, cursor: str | None, limit: int, logger: Any
        ) -> tuple[list[dict], str | None]:
            return pages[cursor]

        monkeypatch.setattr(huntr, "_fetch_page", fake_fetch)
        monkeypatch.setattr(huntr, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            access_token="huntr-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_no_next_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([{"id": "a"}, {"id": "b"}], None)})
        assert rows == [{"id": "a"}, {"id": "b"}]
        # `next` is null, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_cursor_until_next_is_null(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {None: ([{"id": "a"}], "a"), "a": ([{"id": "b"}], None)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "a"}, {"id": "b"}]
        # State is saved after the first page (cursor advances to "a"), then the null cursor stops us.
        assert [s.next for s in manager.saved] == ["a"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(HuntrResumeConfig(next="a"))
        # The first (cursorless) page must never be fetched on resume.
        pages: dict[str | None, tuple[list[dict], str | None]] = {"a": ([{"id": "b"}], None)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "b"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([], None)})
        assert rows == []
        assert manager.saved == []

    def test_empty_page_with_next_terminates(self, monkeypatch: Any) -> None:
        # A lingering cursor on an empty page must not loop forever.
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([], "a")})
        assert rows == []
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"data": []}
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
        with pytest.raises(HuntrRetryableError):
            _fetch_page_unwrapped(session, "/members", None, PAGE_SIZE, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/members", None, PAGE_SIZE, MagicMock())

    def test_success_returns_items_and_next_cursor(self) -> None:
        session = self._session_returning(200, {"data": [{"id": "a"}], "next": "a"})
        items, next_cursor = _fetch_page_unwrapped(session, "/members", None, PAGE_SIZE, MagicMock())
        assert items == [{"id": "a"}]
        assert next_cursor == "a"

    def test_missing_next_key_yields_none_cursor(self) -> None:
        session = self._session_returning(200, {"data": [{"id": "a"}]})
        items, next_cursor = _fetch_page_unwrapped(session, "/members", None, PAGE_SIZE, MagicMock())
        assert items == [{"id": "a"}]
        assert next_cursor is None

    def test_null_next_yields_none_cursor(self) -> None:
        session = self._session_returning(200, {"data": [{"id": "a"}], "next": None})
        _, next_cursor = _fetch_page_unwrapped(session, "/members", None, PAGE_SIZE, MagicMock())
        assert next_cursor is None

    def test_non_dict_body_is_retryable(self) -> None:
        session = self._session_returning(200, [{"id": "a"}])
        with pytest.raises(HuntrRetryableError):
            _fetch_page_unwrapped(session, "/members", None, PAGE_SIZE, MagicMock())

    def test_non_list_data_field_is_retryable(self) -> None:
        session = self._session_returning(200, {"data": {"id": "a"}})
        with pytest.raises(HuntrRetryableError):
            _fetch_page_unwrapped(session, "/members", None, PAGE_SIZE, MagicMock())

    def test_first_request_omits_next_param(self) -> None:
        session = self._session_returning(200, {"data": []})
        _fetch_page_unwrapped(session, "/jobs", None, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE}

    def test_subsequent_request_passes_next_cursor(self) -> None:
        session = self._session_returning(200, {"data": []})
        _fetch_page_unwrapped(session, "/jobs", "cursor-123", PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE, "next": "cursor-123"}


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(huntr, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Huntr returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("huntr-token") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("huntr-token")
        assert status == 0
        assert message is not None and "boom" in message

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Huntr access token"),
            (403, False, "Invalid Huntr access token"),
            (500, False, "Huntr returned HTTP 500"),
        ],
    )
    def test_validate_credentials(
        self, status: int, expected_valid: bool, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._patch_session(monkeypatch, response)
        assert validate_credentials("huntr-token") == (expected_valid, expected_message)


class TestHuntrSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = huntr_source(
            access_token="huntr-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in HUNTR_ENDPOINTS.values())
        assert set(HUNTR_ENDPOINTS) == set(ENDPOINTS)
