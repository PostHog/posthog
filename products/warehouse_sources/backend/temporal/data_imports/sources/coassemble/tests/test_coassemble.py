from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble import coassemble
from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.coassemble import (
    COASSEMBLE_BASE_URL,
    PAGE_SIZE,
    CoassembleResumeConfig,
    CoassembleRetryableError,
    _headers,
    check_access,
    coassemble_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.settings import (
    COASSEMBLE_ENDPOINTS,
    ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = coassemble._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: CoassembleResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[CoassembleResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> CoassembleResumeConfig | None:
        return self._state

    def save_state(self, data: CoassembleResumeConfig) -> None:
        self.saved.append(data)


def _page(prefix: str, start: int, count: int) -> list[dict[str, Any]]:
    return [{"id": f"{prefix}-{i}"} for i in range(start, start + count)]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[tuple[str, int], list[dict]],
        endpoint: str = "courses",
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, page: int, logger: Any, extra_params: Any = None) -> list[dict]:
            return pages.get((path, page), [])

        monkeypatch.setattr(coassemble, "_fetch_page", fake_fetch)
        monkeypatch.setattr(coassemble, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            workspace_id="ws-1",
            api_key="sk-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_short_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {("/courses", 0): _page("c", 0, 2)})
        assert rows == _page("c", 0, 2)
        # A short first page ends the sync; state is still saved after the yield so a crash
        # mid-persist re-fetches only the final page.
        assert [s.next_page for s in manager.saved] == [1]

    def test_full_page_advances_until_short_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {("/courses", 0): _page("c", 0, PAGE_SIZE), ("/courses", 1): _page("c", PAGE_SIZE, 3)}
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 3
        assert [s.next_page for s in manager.saved] == [1, 2]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(CoassembleResumeConfig(next_page=2))
        # Pages 0 and 1 must never be fetched on resume; the pages dict only knows page 2.
        rows = self._collect(manager, monkeypatch, {("/courses", 2): _page("c", 0, 1)})
        assert rows == _page("c", 0, 1)

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {})
        assert rows == []
        assert manager.saved == []


class TestTrackingFanOut:
    @staticmethod
    def _run(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        courses: list[dict],
        trackings: dict[tuple[int, int], list[dict]],
    ) -> tuple[list[dict], list[dict[str, Any]]]:
        calls: list[dict[str, Any]] = []

        def fake_fetch(session: Any, path: str, page: int, logger: Any, extra_params: Any = None) -> list[dict]:
            calls.append({"path": path, "page": page, "extra_params": extra_params})
            if path == "/courses":
                return courses if page == 0 else []
            assert extra_params is not None
            return trackings.get((extra_params["id"], page), [])

        monkeypatch.setattr(coassemble, "_fetch_page", fake_fetch)
        monkeypatch.setattr(coassemble, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            workspace_id="ws-1",
            api_key="sk-key",
            endpoint="course_trackings",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows, calls

    def test_iterates_courses_and_injects_course_id(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        courses = [{"id": 11}, {"id": 22}]
        trackings = {(11, 0): [{"id": 1}, {"id": 2}], (22, 0): [{"id": 3}]}
        rows, _ = self._run(manager, monkeypatch, courses, trackings)
        assert rows == [
            {"id": 1, "course_id": 11},
            {"id": 2, "course_id": 11},
            {"id": 3, "course_id": 22},
        ]
        # Each course is marked completed after its pages are exhausted.
        assert manager.saved[-1].completed_course_ids == [11, 22]
        assert manager.saved[-1].current_course_id is None

    def test_resume_skips_completed_courses_and_starts_at_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(
            CoassembleResumeConfig(next_page=1, completed_course_ids=[11], current_course_id=22)
        )
        courses = [{"id": 11}, {"id": 22}]
        # Only page 1 of course 22 exists in the fixture: fetching course 11 or page 0 of course 22
        # would yield rows that then fail the assertion below.
        trackings = {(22, 1): [{"id": 9}]}
        rows, calls = self._run(manager, monkeypatch, courses, trackings)
        assert rows == [{"id": 9, "course_id": 22}]
        tracking_calls = [c for c in calls if c["path"] == "/trackings"]
        assert all(c["extra_params"]["id"] == 22 for c in tracking_calls)
        assert tracking_calls[0]["page"] == 1

    def test_state_saved_after_each_trackings_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        courses = [{"id": 11}]
        trackings = {
            (11, 0): [{"id": i} for i in range(PAGE_SIZE)],
            (11, 1): [{"id": PAGE_SIZE}],
        }
        self._run(manager, monkeypatch, courses, trackings)
        # Two in-course saves (after each yielded page) then the completion save.
        assert [(s.current_course_id, s.next_page) for s in manager.saved] == [(11, 1), (11, 2), (None, 0)]

    def test_page_cap_stops_runaway_course(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(coassemble, "MAX_TRACKING_PAGES_PER_COURSE", 2)
        manager = _FakeResumableManager()
        courses = [{"id": 11}]
        # Every page is full, so without the cap this would loop past page 2.
        trackings = {(11, page): [{"id": page}] * PAGE_SIZE for page in range(10)}
        rows, calls = self._run(manager, monkeypatch, courses, trackings)
        assert len(rows) == 2 * PAGE_SIZE
        assert len([c for c in calls if c["path"] == "/trackings"]) == 2


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else []
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
        with pytest.raises(CoassembleRetryableError):
            _fetch_page_unwrapped(session, "/courses", 0, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/courses", 0, MagicMock())

    @parameterized.expand(
        [
            ("plain_array", [{"id": 1}]),
            ("data_wrapper", {"data": [{"id": 1}]}),
            ("results_wrapper", {"results": [{"id": 1}]}),
        ]
    )
    def test_accepts_documented_and_wrapped_payloads(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        assert _fetch_page_unwrapped(session, "/courses", 0, MagicMock()) == [{"id": 1}]

    @parameterized.expand([("string", "nope"), ("object_without_list", {"count": 1})])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(CoassembleRetryableError):
            _fetch_page_unwrapped(session, "/courses", 0, MagicMock())

    def test_request_carries_pagination_and_extra_params(self) -> None:
        session = self._session_returning(200, [])
        _fetch_page_unwrapped(session, "/trackings", 3, MagicMock(), extra_params={"id": 42})
        args, kwargs = session.get.call_args
        assert args[0] == f"{COASSEMBLE_BASE_URL}/trackings"
        assert kwargs["params"] == {"page": 3, "length": PAGE_SIZE, "id": 42}


class TestAuthHeaders:
    def test_uses_vendor_specific_authorization_scheme(self) -> None:
        # Coassemble rejects standard schemes (Bearer etc.) with "Invalid Authorization header";
        # the documented format is COASSEMBLE:<workspace_id>:<api_key>.
        assert _headers("ws-1", "sk-key")["Authorization"] == "COASSEMBLE:ws-1:sk-key"


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
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Coassemble returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        with patch.object(coassemble, "make_tracked_session", return_value=self._session(response)):
            assert check_access("ws-1", "sk-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with patch.object(coassemble, "make_tracked_session", return_value=session):
            status, message = check_access("ws-1", "sk-key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Coassemble workspace ID or API key"),
            ("forbidden", 403, False, "Invalid Coassemble workspace ID or API key"),
            ("server_error", 500, False, "Coassemble returned HTTP 500"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        with patch.object(coassemble, "make_tracked_session", return_value=self._session(response)):
            assert validate_credentials("ws-1", "sk-key") == (expected_valid, expected_message)


class TestCoassembleSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = coassemble_source(
            workspace_id="ws-1",
            api_key="sk-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == COASSEMBLE_ENDPOINTS[endpoint].primary_keys
        # Trackings/courses only guarantee mutable progress timestamps, so we don't partition.
        assert response.partition_mode is None

    def test_trackings_key_includes_injected_course_id(self) -> None:
        # Tracking rows are aggregated across every course; without the parent id in the key,
        # per-course id collisions would seed duplicate rows that every later merge multi-matches.
        assert COASSEMBLE_ENDPOINTS["course_trackings"].primary_keys == ["course_id", "id"]

    def test_clients_and_users_use_identifier_keys(self) -> None:
        # Neither object carries a numeric `id` in the API response.
        assert COASSEMBLE_ENDPOINTS["clients"].primary_keys == ["clientIdentifier"]
        assert COASSEMBLE_ENDPOINTS["users"].primary_keys == ["identifier"]
