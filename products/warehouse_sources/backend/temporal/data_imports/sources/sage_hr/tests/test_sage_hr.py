from collections.abc import Mapping
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.sage_hr import sage_hr
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_hr.sage_hr import (
    SageHRResumeConfig,
    SageHRRetryableError,
    _iter_windows,
    check_access,
    get_rows,
    normalize_subdomain,
    sage_hr_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_hr.settings import (
    ENDPOINTS,
    SAGE_HR_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = sage_hr._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: SageHRResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SageHRResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SageHRResumeConfig | None:
        return self._state

    def save_state(self, data: SageHRResumeConfig) -> None:
        self.saved.append(data)


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("bare", "acme", "acme"),
            ("full_host", "acme.sage.hr", "acme"),
            ("https_prefix", "https://acme.sage.hr/", "acme"),
            ("whitespace", "  acme  ", "acme"),
            ("hyphenated", "acme-co", "acme-co"),
        ]
    )
    def test_accepts_and_cleans_valid_input(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected

    @parameterized.expand(
        [
            ("path_injection", "acme.sage.hr/../internal"),
            ("other_domain", "evil.com"),
            ("embedded_at", "acme@evil.com"),
            ("empty", ""),
            ("space_inside", "ac me"),
        ]
    )
    def test_rejects_host_retargeting_input(self, _name: str, raw: str) -> None:
        # The subdomain becomes the request host carrying the API key — anything that isn't a single
        # DNS label must be rejected before a URL is built.
        with pytest.raises(ValueError):
            normalize_subdomain(raw)


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
        with pytest.raises(SageHRRetryableError):
            _fetch_page_unwrapped(session, "https://acme.sage.hr/api/employees?page=1", MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "https://acme.sage.hr/api/employees?page=1", MagicMock())

    def test_success_returns_items_and_next_page(self) -> None:
        session = self._session_returning(200, {"data": [{"id": 1}], "meta": {"current_page": 1, "next_page": 2}})
        items, next_page = _fetch_page_unwrapped(session, "https://acme.sage.hr/api/employees?page=1", MagicMock())
        assert items == [{"id": 1}]
        assert next_page == 2

    @parameterized.expand(
        [
            ("null_next_page", {"data": [{"id": 1}], "meta": {"current_page": 2, "next_page": None}}),
            ("missing_meta", {"data": [{"id": 1}]}),
            ("non_dict_meta", {"data": [{"id": 1}], "meta": "nope"}),
        ]
    )
    def test_last_or_unpaginated_page_yields_none_next_page(self, _name: str, body: dict) -> None:
        session = self._session_returning(200, body)
        items, next_page = _fetch_page_unwrapped(session, "https://acme.sage.hr/api/employees", MagicMock())
        assert items == [{"id": 1}]
        assert next_page is None

    @parameterized.expand(
        [
            ("non_dict_body", [{"id": 1}]),
            ("non_list_data", {"data": {"id": 1}}),
        ]
    )
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(SageHRRetryableError):
            _fetch_page_unwrapped(session, "https://acme.sage.hr/api/employees", MagicMock())


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: Mapping[str, tuple[list[dict], int | None]],
        endpoint: str,
        requested: list[str] | None = None,
    ) -> list[dict]:
        """Drive get_rows with _fetch_page faked by URL query string (sorted for determinism)."""

        def fake_fetch(session: Any, url: str, logger: Any) -> tuple[list[dict], int | None]:
            parsed = urlparse(url)
            key = "&".join(f"{k}={v[0]}" for k, v in sorted(parse_qs(parsed.query).items()))
            if requested is not None:
                requested.append(key)
            return pages[key]

        monkeypatch.setattr(sage_hr, "_fetch_page", fake_fetch)
        monkeypatch.setattr(sage_hr, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            subdomain="acme",
            api_key="sage-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_no_next_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {"page=1": ([{"id": 1}, {"id": 2}], None)}, "employees")
        assert rows == [{"id": 1}, {"id": 2}]
        # `meta.next_page` is null, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_next_page_until_null(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {"page=1": ([{"id": 1}], 2), "page=2": ([{"id": 2}], None)}
        rows = self._collect(manager, monkeypatch, pages, "employees")
        assert rows == [{"id": 1}, {"id": 2}]
        # State is saved after the first page (advancing to page 2), then the null next_page stops us.
        assert [(s.next_page, s.window_from) for s in manager.saved] == [(2, None)]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SageHRResumeConfig(next_page=2))
        # Page 1 must never be fetched on resume.
        pages = {"page=2": ([{"id": 2}], None)}
        rows = self._collect(manager, monkeypatch, pages, "employees")
        assert rows == [{"id": 2}]

    @pytest.mark.parametrize(
        "pages",
        [
            pytest.param({"page=1": ([], 2)}, id="empty_page_with_next"),
            pytest.param({"page=1": ([{"id": 1}], 1)}, id="non_advancing_next_page"),
        ],
    )
    def test_bad_meta_terminates_instead_of_looping(
        self, pages: dict[str, tuple[list[dict], int | None]], monkeypatch: Any
    ) -> None:
        manager = _FakeResumableManager()
        self._collect(manager, monkeypatch, pages, "employees")
        assert manager.saved == []

    def test_unpaginated_endpoint_fetches_once_without_page_param(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        requested: list[str] = []
        rows = self._collect(manager, monkeypatch, {"": ([{"id": 1}], None)}, "leave_policies", requested)
        assert rows == [{"id": 1}]
        assert requested == [""]
        assert manager.saved == []


class TestWindowedLeaveRequests:
    RANGE = (date(2024, 1, 1), date(2024, 3, 31))

    def _collect(
        self,
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: Mapping[str, tuple[list[dict], int | None]],
        requested: list[str] | None = None,
    ) -> list[dict]:
        monkeypatch.setattr(sage_hr, "_leave_window_range", lambda: self.RANGE)
        return TestGetRows._collect(manager, monkeypatch, pages, "leave_requests", requested)

    def test_iter_windows_are_contiguous_and_capped(self) -> None:
        windows = list(_iter_windows(*self.RANGE))
        assert windows[0][0] == self.RANGE[0]
        assert windows[-1][1] == self.RANGE[1]
        for window_start, window_end in windows:
            # The API rejects `from`/`to` ranges of 65 days or more.
            assert (window_end - window_start).days < 65
        for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
            assert (next_start - prev_end).days == 1

    def test_walks_every_window_with_from_to_params(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        requested: list[str] = []
        pages = {
            "from=2024-01-01&page=1&to=2024-02-29": ([{"id": 1}], None),
            "from=2024-03-01&page=1&to=2024-03-31": ([{"id": 2}], None),
        }
        rows = self._collect(manager, monkeypatch, pages, requested)
        assert rows == [{"id": 1}, {"id": 2}]
        assert requested == list(pages.keys())
        # Window advance is persisted so a resume skips the exhausted window.
        assert [(s.next_page, s.window_from) for s in manager.saved] == [(1, "2024-03-01")]

    def test_paginates_within_a_window_and_saves_state_after_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            "from=2024-01-01&page=1&to=2024-02-29": ([{"id": 1}], 2),
            "from=2024-01-01&page=2&to=2024-02-29": ([{"id": 2}], None),
            "from=2024-03-01&page=1&to=2024-03-31": ([], None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 1}, {"id": 2}]
        assert [(s.next_page, s.window_from) for s in manager.saved] == [(2, "2024-01-01"), (1, "2024-03-01")]

    def test_dedupes_rows_returned_by_adjacent_windows(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        # A request spanning the window boundary comes back from both windows; full-refresh batches
        # append without merging, so the second occurrence must be dropped.
        pages = {
            "from=2024-01-01&page=1&to=2024-02-29": ([{"id": 1}, {"id": 7}], None),
            "from=2024-03-01&page=1&to=2024-03-31": ([{"id": 7}, {"id": 2}], None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 1}, {"id": 7}, {"id": 2}]

    def test_resumes_from_saved_window_and_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SageHRResumeConfig(next_page=2, window_from="2024-03-01"))
        # Earlier windows and page 1 of the resumed window must never be fetched.
        pages = {"from=2024-03-01&page=2&to=2024-03-31": ([{"id": 2}], None)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 2}]


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(sage_hr, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, expected_status, expected_message",
        [
            (200, 200, None),
            (401, 401, None),
            (403, 403, None),
            (404, 404, "Sage HR company subdomain not found. Use the subdomain from your Sage HR URL."),
            (500, 500, "Sage HR returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._patch_session(monkeypatch, response)
        assert check_access("acme", "sage-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("acme", "sage-key")
        assert status == 0
        assert message is not None and "Could not connect" in message

    def test_invalid_subdomain_fails_without_network(self, monkeypatch: Any) -> None:
        session = self._patch_session(monkeypatch, MagicMock())
        status, message = check_access("evil.com/#", "sage-key")
        assert status == 0
        assert message is not None and "Invalid Sage HR company subdomain" in message
        session.get.assert_not_called()

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (
                401,
                False,
                "Invalid Sage HR API key. Make sure API access is enabled under Settings → Integrations → API.",
            ),
            (
                403,
                False,
                "Your Sage HR API key does not have access to this data. Check that API access is enabled under Settings → Integrations → API.",
            ),
            (500, False, "Sage HR returned HTTP 500"),
        ],
    )
    def test_validate_credentials(
        self, status: int, expected_valid: bool, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._patch_session(monkeypatch, response)
        assert validate_credentials("acme", "sage-key") == (expected_valid, expected_message)


class TestSageHRSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = sage_hr_source(
            subdomain="acme",
            api_key="sage-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SAGE_HR_ENDPOINTS.values())
        assert set(SAGE_HR_ENDPOINTS) == set(ENDPOINTS)
