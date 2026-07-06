import base64
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack import partnerstack
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.partnerstack import (
    PAGE_SIZE,
    PartnerStackResumeConfig,
    PartnerStackRetryableError,
    _headers,
    check_access,
    get_rows,
    partnerstack_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.settings import (
    ENDPOINTS,
    PARTNERSTACK_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = partnerstack._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: PartnerStackResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PartnerStackResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PartnerStackResumeConfig | None:
        return self._state

    def save_state(self, data: PartnerStackResumeConfig) -> None:
        self.saved.append(data)


class TestHeaders:
    def test_builds_basic_auth_header(self) -> None:
        headers = _headers("pub", "priv")
        expected = base64.b64encode(b"pub:priv").decode("ascii")
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["Accept"] == "application/json"


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str | None, tuple[list[dict], bool]],
        endpoint: str = "partnerships",
    ) -> list[dict]:
        def fake_fetch(
            session: Any, path: str, starting_after: str | None, limit: int, logger: Any
        ) -> tuple[list[dict], bool]:
            return pages[starting_after]

        monkeypatch.setattr(partnerstack, "_fetch_page", fake_fetch)
        monkeypatch.setattr(partnerstack, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            public_key="pub",
            private_key="priv",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_no_more_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([{"key": "a"}, {"key": "b"}], False)})
        assert rows == [{"key": "a"}, {"key": "b"}]
        # has_more is false, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_cursor_until_has_more_false(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            None: ([{"key": "a"}, {"key": "b"}], True),
            "b": ([{"key": "c"}], False),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"key": "a"}, {"key": "b"}, {"key": "c"}]
        # State is saved after the first page (cursor advances to the last key "b"), then we stop.
        assert [s.starting_after for s in manager.saved] == ["b"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PartnerStackResumeConfig(starting_after="b"))
        # The initial (cursor=None) page must never be fetched on resume.
        pages = {"b": ([{"key": "c"}], False)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"key": "c"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([], False)})
        assert rows == []
        assert manager.saved == []

    def test_stops_when_last_object_missing_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        # has_more is true but the last object has no `key`, so we can't advance and must stop.
        rows = self._collect(manager, monkeypatch, {None: ([{"no_key": 1}], True)})
        assert rows == [{"no_key": 1}]
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"data": {"items": [], "has_more": False}}
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
        with pytest.raises(PartnerStackRetryableError):
            _fetch_page_unwrapped(session, "/partnerships", None, PAGE_SIZE, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/partnerships", None, PAGE_SIZE, MagicMock())

    def test_success_returns_items_and_has_more(self) -> None:
        body = {"data": {"items": [{"key": "a"}], "has_more": True}}
        session = self._session_returning(200, body)
        items, has_more = _fetch_page_unwrapped(session, "/partnerships", None, PAGE_SIZE, MagicMock())
        assert items == [{"key": "a"}]
        assert has_more is True

    def test_missing_has_more_defaults_to_false(self) -> None:
        body = {"data": {"items": [{"key": "a"}]}}
        session = self._session_returning(200, body)
        _, has_more = _fetch_page_unwrapped(session, "/partnerships", None, PAGE_SIZE, MagicMock())
        assert has_more is False

    @parameterized.expand(
        [
            ("bare_list", [{"key": "a"}]),
            ("missing_data", {"items": []}),
            ("data_not_dict", {"data": []}),
        ]
    )
    def test_unexpected_envelope_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(PartnerStackRetryableError):
            _fetch_page_unwrapped(session, "/partnerships", None, PAGE_SIZE, MagicMock())

    def test_non_list_items_is_retryable(self) -> None:
        session = self._session_returning(200, {"data": {"items": "nope", "has_more": False}})
        with pytest.raises(PartnerStackRetryableError):
            _fetch_page_unwrapped(session, "/partnerships", None, PAGE_SIZE, MagicMock())

    def test_request_omits_cursor_on_first_page(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "/customers", None, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE}

    def test_request_includes_cursor_when_set(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "/customers", "abc", PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"limit": PAGE_SIZE, "starting_after": "abc"}


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(partnerstack, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "PartnerStack returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("pub", "priv") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("pub", "priv")
        assert status == 0
        assert message is not None and "boom" in message

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid PartnerStack API keys"),
            (403, False, "Invalid PartnerStack API keys"),
            (500, False, "PartnerStack returned HTTP 500"),
        ],
    )
    def test_validate_credentials(
        self, status: int, expected_valid: bool, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._patch_session(monkeypatch, response)
        assert validate_credentials("pub", "priv") == (expected_valid, expected_message)


class TestPartnerStackSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = partnerstack_source(
            public_key="pub",
            private_key="priv",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["key"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_key_primary_key(self) -> None:
        assert all(config.primary_keys == ["key"] for config in PARTNERSTACK_ENDPOINTS.values())
        assert set(PARTNERSTACK_ENDPOINTS) == set(ENDPOINTS)
