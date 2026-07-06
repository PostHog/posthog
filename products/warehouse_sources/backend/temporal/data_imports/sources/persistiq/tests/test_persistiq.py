from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq import persistiq
from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.persistiq import (
    PersistiqResumeConfig,
    PersistiqRetryableError,
    check_access,
    get_rows,
    persistiq_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.settings import (
    ENDPOINTS,
    PERSISTIQ_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = persistiq._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: PersistiqResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PersistiqResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PersistiqResumeConfig | None:
        return self._state

    def save_state(self, data: PersistiqResumeConfig) -> None:
        self.saved.append(data)


def _page(items: list[dict], has_more: bool, list_key: str = "leads") -> dict[str, Any]:
    return {list_key: items, "has_more": has_more, "next_page": None}


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager, monkeypatch: Any, pages: dict[int, dict], endpoint: str = "leads"
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, page: int, logger: Any) -> dict:
            return pages[page]

        monkeypatch.setattr(persistiq, "_fetch_page", fake_fetch)
        monkeypatch.setattr(persistiq, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="pq-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_yields_items_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page([{"id": "l_1"}, {"id": "l_2"}], has_more=False)})
        assert rows == [{"id": "l_1"}, {"id": "l_2"}]
        # No further pages, so no resume state is persisted.
        assert manager.saved == []

    def test_follows_pagination_until_has_more_is_false(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            1: _page([{"id": "l_1"}], has_more=True),
            2: _page([{"id": "l_2"}], has_more=True),
            3: _page([{"id": "l_3"}], has_more=False),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "l_1"}, {"id": "l_2"}, {"id": "l_3"}]

    def test_saves_next_page_after_yielding_each_batch(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            1: _page([{"id": "l_1"}], has_more=True),
            2: _page([{"id": "l_2"}], has_more=False),
        }
        self._collect(manager, monkeypatch, pages)
        # State is saved AFTER page 1 is yielded (pointing at page 2), and never for the final page.
        assert [s.next_page for s in manager.saved] == [2]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PersistiqResumeConfig(next_page=2))
        pages = {
            # Page 1 must never be fetched on resume.
            2: _page([{"id": "l_2"}], has_more=True),
            3: _page([{"id": "l_3"}], has_more=False),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "l_2"}, {"id": "l_3"}]

    def test_empty_items_does_not_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page([], has_more=False)})
        assert rows == []

    def test_uses_endpoint_specific_list_key(self, monkeypatch: Any) -> None:
        # `users` reads rows from the "users" envelope key, not "leads".
        manager = _FakeResumableManager()
        pages = {1: _page([{"id": "u_1"}], has_more=False, list_key="users")}
        rows = self._collect(manager, monkeypatch, pages, endpoint="users")
        assert rows == [{"id": "u_1"}]

    def test_missing_list_key_raises(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()

        def fake_fetch(session: Any, path: str, page: int, logger: Any) -> dict:
            return {"has_more": False}

        monkeypatch.setattr(persistiq, "_fetch_page", fake_fetch)
        monkeypatch.setattr(persistiq, "make_tracked_session", lambda **kwargs: MagicMock())

        with pytest.raises(PersistiqRetryableError):
            list(
                get_rows(
                    api_key="pq-key",
                    endpoint="leads",
                    logger=MagicMock(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                )
            )


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {}
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
        with pytest.raises(PersistiqRetryableError):
            _fetch_page_unwrapped(session, "/leads", 1, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/leads", 1, MagicMock())

    def test_success_returns_json_body(self) -> None:
        body = _page([{"id": "l_1"}], has_more=False)
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "/leads", 1, MagicMock())
        assert result == body

    def test_non_dict_body_is_retryable(self) -> None:
        session = self._session_returning(200, [{"id": "l_1"}])
        with pytest.raises(PersistiqRetryableError):
            _fetch_page_unwrapped(session, "/leads", 1, MagicMock())

    def test_request_uses_page_param(self) -> None:
        session = self._session_returning(200, _page([], has_more=False))
        _fetch_page_unwrapped(session, "/campaigns", 3, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"page": 3}


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(persistiq, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "PersistIQ returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("pq-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("pq-key")
        assert status == 0
        assert message is not None and "boom" in message

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid PersistIQ API key"),
            (403, False, "Invalid PersistIQ API key"),
            (500, False, "PersistIQ returned HTTP 500"),
        ],
    )
    def test_validate_credentials(
        self, status: int, expected_valid: bool, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._patch_session(monkeypatch, response)
        assert validate_credentials("pq-key") == (expected_valid, expected_message)


class TestPersistiqSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = persistiq_source(
            api_key="pq-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in PERSISTIQ_ENDPOINTS.values())
        assert set(PERSISTIQ_ENDPOINTS) == set(ENDPOINTS)
