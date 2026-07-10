from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.luma import luma
from products.warehouse_sources.backend.temporal.data_imports.sources.luma.luma import (
    LUMA_BASE_URL,
    LumaResumeConfig,
    LumaRetryableError,
    check_access,
    get_rows,
    luma_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.luma.settings import (
    ENDPOINTS,
    EVENTS_PATH,
    GUESTS_PATH,
    LUMA_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = luma._fetch_page.__wrapped__  # type: ignore[attr-defined]

# Keyed by (path, cursor); the fan-out variant adds the parent event api_id. Annotated on the
# literals below so mypy doesn't narrow all-None keys to an incompatible invariant dict type.
PageMap = dict[tuple[str, str | None], tuple[list[dict], Optional[str]]]
FanOutPageMap = dict[tuple[str, str | None, str | None], tuple[list[dict], Optional[str]]]


class _FakeResumableManager:
    def __init__(self, state: LumaResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[LumaResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> LumaResumeConfig | None:
        return self._state

    def save_state(self, data: LumaResumeConfig) -> None:
        self.saved.append(data)


def _page_router(pages: PageMap) -> Any:
    def fake_fetch(
        session: Any, path: str, cursor: str | None, logger: Any, extra_params: dict | None = None
    ) -> tuple[list[dict], Optional[str]]:
        return pages[(path, cursor)]

    return fake_fetch


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: PageMap,
        endpoint: str,
    ) -> list[dict]:
        monkeypatch.setattr(luma, "_fetch_page", _page_router(pages))
        monkeypatch.setattr(luma, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="luma-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_yields_flattened_events_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: PageMap = {
            (EVENTS_PATH, None): (
                [{"api_id": "evt-1", "event": {"api_id": "evt-1", "name": "Meetup"}}],
                None,
            )
        }
        rows = self._collect(manager, monkeypatch, pages, "events")
        # The `event` envelope is unwrapped so columns are top-level.
        assert rows == [{"api_id": "evt-1", "name": "Meetup"}]
        # No next cursor means the sync ends without persisting resume state.
        assert manager.saved == []

    def test_follows_cursor_and_saves_state_after_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        path = LUMA_ENDPOINTS["people"].path
        pages: PageMap = {
            (path, None): ([{"api_id": "per-1"}], "cur-2"),
            (path, "cur-2"): ([{"api_id": "per-2"}], None),
        }
        rows = self._collect(manager, monkeypatch, pages, "people")
        assert rows == [{"api_id": "per-1"}, {"api_id": "per-2"}]
        # State is saved once — after the first page, pointing at the next cursor — then we stop.
        assert [s.pagination_cursor for s in manager.saved] == ["cur-2"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(LumaResumeConfig(pagination_cursor="cur-2"))
        path = LUMA_ENDPOINTS["people"].path
        # The first page must never be fetched on resume.
        pages: PageMap = {(path, "cur-2"): ([{"api_id": "per-2"}], None)}
        rows = self._collect(manager, monkeypatch, pages, "people")
        assert rows == [{"api_id": "per-2"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: PageMap = {(LUMA_ENDPOINTS["person_tags"].path, None): ([], None)}
        rows = self._collect(manager, monkeypatch, pages, "person_tags")
        assert rows == []
        assert manager.saved == []

    def test_entry_without_envelope_is_yielded_as_is(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        # Defensive path: if an events entry has no nested `event` object we keep the raw entry.
        pages: PageMap = {(EVENTS_PATH, None): ([{"api_id": "evt-9"}], None)}
        rows = self._collect(manager, monkeypatch, pages, "events")
        assert rows == [{"api_id": "evt-9"}]


class TestGuestsFanOut:
    def _collect(
        self,
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: FanOutPageMap,
    ) -> list[dict]:
        def fake_fetch(
            session: Any, path: str, cursor: str | None, logger: Any, extra_params: dict | None = None
        ) -> tuple[list[dict], Optional[str]]:
            event_api_id = (extra_params or {}).get("event_api_id")
            return pages[(path, cursor, event_api_id)]

        monkeypatch.setattr(luma, "_fetch_page", fake_fetch)
        monkeypatch.setattr(luma, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="luma-key",
            endpoint="guests",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_rows_carry_parent_event_api_id(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: FanOutPageMap = {
            (EVENTS_PATH, None, None): (
                [
                    {"api_id": "evt-1", "event": {"api_id": "evt-1"}},
                    {"api_id": "evt-2", "event": {"api_id": "evt-2"}},
                ],
                None,
            ),
            (GUESTS_PATH, None, "evt-1"): (
                [{"api_id": "gst-a", "guest": {"api_id": "gst-a", "name": "Ada"}}],
                None,
            ),
            (GUESTS_PATH, None, "evt-2"): ([], None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        # The `guest` envelope is unwrapped and the parent event id injected for the composite key.
        assert rows == [{"api_id": "gst-a", "name": "Ada", "event_api_id": "evt-1"}]
        assert manager.saved == []

    def test_paginates_guests_within_an_event(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: FanOutPageMap = {
            (EVENTS_PATH, None, None): ([{"api_id": "evt-1", "event": {"api_id": "evt-1"}}], None),
            (GUESTS_PATH, None, "evt-1"): ([{"api_id": "gst-a", "guest": {"api_id": "gst-a"}}], "gcur-2"),
            (GUESTS_PATH, "gcur-2", "evt-1"): ([{"api_id": "gst-b", "guest": {"api_id": "gst-b"}}], None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert [r["api_id"] for r in rows] == ["gst-a", "gst-b"]

    def test_saves_events_cursor_after_finishing_events_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: FanOutPageMap = {
            (EVENTS_PATH, None, None): ([{"api_id": "evt-1", "event": {"api_id": "evt-1"}}], "ecur-2"),
            (EVENTS_PATH, "ecur-2", None): ([{"api_id": "evt-2", "event": {"api_id": "evt-2"}}], None),
            (GUESTS_PATH, None, "evt-1"): ([{"api_id": "gst-a", "guest": {"api_id": "gst-a"}}], None),
            (GUESTS_PATH, None, "evt-2"): ([{"api_id": "gst-b", "guest": {"api_id": "gst-b"}}], None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert [r["event_api_id"] for r in rows] == ["evt-1", "evt-2"]
        # State points at the next *events* page, saved only after all its guests were yielded.
        assert [s.pagination_cursor for s in manager.saved] == ["ecur-2"]

    def test_resumes_from_saved_events_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(LumaResumeConfig(pagination_cursor="ecur-2"))
        # The first events page must never be fetched on resume.
        pages: FanOutPageMap = {
            (EVENTS_PATH, "ecur-2", None): ([{"api_id": "evt-2", "event": {"api_id": "evt-2"}}], None),
            (GUESTS_PATH, None, "evt-2"): ([{"api_id": "gst-b", "guest": {"api_id": "gst-b"}}], None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"api_id": "gst-b", "event_api_id": "evt-2"}]


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"entries": [], "has_more": False}
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
        with pytest.raises(LumaRetryableError):
            _fetch_page_unwrapped(session, EVENTS_PATH, None, MagicMock())

    @parameterized.expand([("bad_request", 400), ("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, EVENTS_PATH, None, MagicMock())

    def test_success_returns_entries_and_next_cursor(self) -> None:
        body = {"entries": [{"api_id": "evt-1"}], "has_more": True, "next_cursor": "cur-2"}
        session = self._session_returning(200, body)
        rows, next_cursor = _fetch_page_unwrapped(session, EVENTS_PATH, None, MagicMock())
        assert rows == [{"api_id": "evt-1"}]
        assert next_cursor == "cur-2"

    @parameterized.expand(
        [
            ("has_more_false", {"entries": [{"api_id": "a"}], "has_more": False, "next_cursor": "cur-2"}),
            ("missing_next_cursor", {"entries": [{"api_id": "a"}], "has_more": True}),
            ("empty_next_cursor", {"entries": [{"api_id": "a"}], "has_more": True, "next_cursor": ""}),
        ]
    )
    def test_pagination_terminates(self, _name: str, body: dict) -> None:
        # `has_more` is authoritative — a lingering cursor on the final page must not loop forever.
        session = self._session_returning(200, body)
        _, next_cursor = _fetch_page_unwrapped(session, EVENTS_PATH, None, MagicMock())
        assert next_cursor is None

    @parameterized.expand([("bare_list", [{"api_id": "a"}]), ("missing_entries", {"has_more": False})])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(LumaRetryableError):
            _fetch_page_unwrapped(session, EVENTS_PATH, None, MagicMock())

    def test_request_params_include_cursor_and_extras(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, GUESTS_PATH, "cur-9", MagicMock(), extra_params={"event_api_id": "evt-1"})
        args, kwargs = session.get.call_args
        assert args[0] == f"{LUMA_BASE_URL}{GUESTS_PATH}"
        assert kwargs["params"]["pagination_cursor"] == "cur-9"
        assert kwargs["params"]["event_api_id"] == "evt-1"
        assert kwargs["params"]["pagination_limit"] == luma.PAGE_SIZE

    def test_first_request_omits_cursor(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, EVENTS_PATH, None, MagicMock())
        _, kwargs = session.get.call_args
        assert "pagination_cursor" not in kwargs["params"]


class TestCheckAccess:
    def _session(self, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("missing_key", 400, False, 400, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Luma returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        with patch.object(luma, "make_tracked_session", return_value=self._session(response)):
            assert check_access("luma-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with patch.object(luma, "make_tracked_session", return_value=session):
            status, message = check_access("luma-key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("missing_key", 400, False, "Invalid Luma API key"),
            ("unauthorized", 401, False, "Invalid Luma API key"),
            ("forbidden", 403, False, "Invalid Luma API key"),
            ("server_error", 500, False, "Luma returned HTTP 500"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        with patch.object(luma, "make_tracked_session", return_value=self._session(response)):
            assert validate_credentials("luma-key") == (expected_valid, expected_message)


class TestLumaSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = luma_source(
            api_key="luma-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == LUMA_ENDPOINTS[endpoint].primary_keys
        # `created_at` is nullable in Luma payloads, so we don't partition on it.
        assert response.partition_mode is None

    def test_guests_primary_key_includes_parent_event(self) -> None:
        # Guest rows aggregate across every event, so the key must be unique table-wide.
        assert LUMA_ENDPOINTS["guests"].primary_keys == ["event_api_id", "api_id"]
