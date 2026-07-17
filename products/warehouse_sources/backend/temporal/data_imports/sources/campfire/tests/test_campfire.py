from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.campfire import campfire
from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.campfire import (
    CampfireResumeConfig,
    _build_first_url,
    _format_incremental_value,
    _parse_page,
    _validate_next_url,
    campfire_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.settings import (
    CAMPFIRE_BASE_URL,
    CAMPFIRE_ENDPOINTS,
    ENDPOINTS,
)


class _FakeResumableManager:
    def __init__(self, state: CampfireResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[CampfireResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> CampfireResumeConfig | None:
        return self._state

    def save_state(self, data: CampfireResumeConfig) -> None:
        self.saved.append(data)


def _session_returning(pages: dict[str, dict[str, Any]]) -> MagicMock:
    """A fake session whose GET returns the page registered for each exact URL."""

    def _get(url: str, **kwargs: Any) -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = pages[url]
        return response

    session = MagicMock()
    session.get.side_effect = _get
    return session


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query, keep_blank_values=True)


class TestBuildFirstUrl:
    def test_windowed_endpoints_request_all_time(self) -> None:
        # Without all_time=true these endpoints silently default to roughly the last six
        # months, truncating the initial sync.
        for endpoint in ("chart_transactions", "journal_entries"):
            url = _build_first_url(CAMPFIRE_ENDPOINTS[endpoint], False, None)
            assert _query(url)["all_time"] == ["true"], endpoint

    def test_cursor_endpoints_send_empty_cursor(self) -> None:
        url = _build_first_url(CAMPFIRE_ENDPOINTS["bill_payments"], False, None)
        assert _query(url)["cursor"] == [""]

    def test_offset_endpoints_do_not_send_cursor(self) -> None:
        url = _build_first_url(CAMPFIRE_ENDPOINTS["vendors"], False, None)
        assert "cursor" not in _query(url)

    def test_incremental_value_becomes_last_modified_filter(self) -> None:
        url = _build_first_url(CAMPFIRE_ENDPOINTS["vendors"], True, datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
        assert _query(url)["last_modified_at__gte"] == ["2026-01-02T03:04:05Z"]

    def test_no_filter_on_full_refresh_or_missing_watermark(self) -> None:
        assert "last_modified_at__gte" not in _query(_build_first_url(CAMPFIRE_ENDPOINTS["vendors"], False, None))
        assert "last_modified_at__gte" not in _query(_build_first_url(CAMPFIRE_ENDPOINTS["vendors"], True, None))

    def test_full_refresh_only_endpoint_never_sends_filter(self) -> None:
        # journal_entries has no server-side last_modified filter; sending one anyway would
        # be silently ignored at best.
        url = _build_first_url(CAMPFIRE_ENDPOINTS["journal_entries"], True, datetime(2026, 1, 1, tzinfo=UTC))
        assert "last_modified_at__gte" not in _query(url)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05Z"),
            ("naive_datetime", datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05Z"),
            ("date", date(2026, 1, 2), "2026-01-02"),
            ("string_passthrough", "2026-01-02T03:04:05Z", "2026-01-02T03:04:05Z"),
        ]
    )
    def test_formats(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestParsePage:
    @parameterized.expand(
        [
            (
                "drf_envelope",
                {"count": 2, "next": "https://x/next", "results": [{"id": 1}]},
                [{"id": 1}],
                "https://x/next",
            ),
            ("null_results", {"count": 0, "next": None, "results": None}, [], None),
            ("bare_list", [{"id": 1}, {"id": 2}], [{"id": 1}, {"id": 2}], None),
            ("unexpected_scalar", "nope", [], None),
        ]
    )
    def test_shapes(self, _name: str, data: Any, expected_rows: list, expected_next: Any) -> None:
        assert _parse_page(data) == (expected_rows, expected_next)


class TestValidateNextUrl:
    def test_same_host_https_is_allowed(self) -> None:
        _validate_next_url(f"{CAMPFIRE_BASE_URL}/coa/api/vendor?offset=100")

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/coa/api/vendor?offset=100"),
            ("http_downgrade", "http://api.meetcampfire.com/coa/api/vendor?offset=100"),
        ]
    )
    def test_off_host_links_are_rejected(self, _name: str, url: str) -> None:
        # The API key rides in a header; following an off-host next link would leak it.
        with pytest.raises(ValueError):
            _validate_next_url(url)


class TestGetRows:
    def test_follows_next_links_and_saves_state_after_each_yield(self) -> None:
        first_url = _build_first_url(CAMPFIRE_ENDPOINTS["vendors"], False, None)
        page2 = f"{CAMPFIRE_BASE_URL}/coa/api/vendor?limit=500&offset=500"
        session = _session_returning(
            {
                first_url: {"count": 3, "next": page2, "results": [{"id": 1}, {"id": 2}]},
                page2: {"count": 3, "next": None, "results": [{"id": 3}]},
            }
        )
        manager = _FakeResumableManager()

        with patch.object(campfire, "make_tracked_session", return_value=session):
            batches = list(get_rows("key", "vendors", MagicMock(), manager))

        assert batches == [[{"id": 1}, {"id": 2}], [{"id": 3}]]
        # State is saved only while more pages remain, so a crash re-yields (not skips) the
        # last page — merge dedupes on the primary key.
        assert [s.next_url for s in manager.saved] == [page2]

    def test_resumes_from_saved_next_url(self) -> None:
        page2 = f"{CAMPFIRE_BASE_URL}/coa/api/vendor?limit=500&offset=500"
        session = _session_returning({page2: {"count": 3, "next": None, "results": [{"id": 3}]}})
        manager = _FakeResumableManager(CampfireResumeConfig(next_url=page2))

        with patch.object(campfire, "make_tracked_session", return_value=session):
            batches = list(get_rows("key", "vendors", MagicMock(), manager))

        assert batches == [[{"id": 3}]]
        session.get.assert_called_once()
        assert session.get.call_args[0][0] == page2

    def test_empty_first_page_yields_nothing(self) -> None:
        first_url = _build_first_url(CAMPFIRE_ENDPOINTS["vendors"], False, None)
        session = _session_returning({first_url: {"count": 0, "next": None, "results": []}})

        with patch.object(campfire, "make_tracked_session", return_value=session):
            batches = list(get_rows("key", "vendors", MagicMock(), _FakeResumableManager()))

        assert batches == []

    def test_off_host_next_link_stops_the_sync(self) -> None:
        first_url = _build_first_url(CAMPFIRE_ENDPOINTS["vendors"], False, None)
        session = _session_returning(
            {first_url: {"count": 1, "next": "https://evil.example.com/x", "results": [{"id": 1}]}}
        )

        with patch.object(campfire, "make_tracked_session", return_value=session):
            with pytest.raises(ValueError):
                list(get_rows("key", "vendors", MagicMock(), _FakeResumableManager()))


class TestFetchRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_are_retried(self, _name: str, status: int) -> None:
        bad = MagicMock(status_code=status)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"results": []}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(campfire._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = campfire._fetch_page(session, f"{CAMPFIRE_BASE_URL}/coa/api/vendor", {}, MagicMock())

        assert result == {"results": []}
        assert session.get.call_count == 2

    def test_client_error_raises_without_retry(self) -> None:
        bad = requests.Response()
        bad.status_code = 401
        bad.url = f"{CAMPFIRE_BASE_URL}/coa/api/vendor"
        session = MagicMock()
        session.get.return_value = bad

        with pytest.raises(requests.HTTPError):
            campfire._fetch_page(session, f"{CAMPFIRE_BASE_URL}/coa/api/vendor", {}, MagicMock())
        assert session.get.call_count == 1


class TestCampfireSourceResponse:
    def test_every_endpoint_builds_a_source_response(self) -> None:
        for endpoint in ENDPOINTS:
            response = campfire_source("key", endpoint, MagicMock(), MagicMock())
            assert response.name == endpoint
            assert response.primary_keys == ["id"]

    def test_payment_sync_endpoints_are_ascending(self) -> None:
        # Campfire documents (last_modified_at, id) ascending order on the payment sync
        # endpoints, which lets the pipeline checkpoint the watermark per batch.
        for endpoint in ("bill_payments", "invoice_payments"):
            assert campfire_source("key", endpoint, MagicMock(), MagicMock()).sort_mode == "asc"

    def test_undocumented_order_endpoints_are_descending(self) -> None:
        # Everything else has no documented response order, so the watermark must only be
        # persisted once the sync completes.
        for endpoint in ("chart_transactions", "vendors", "contracts"):
            assert campfire_source("key", endpoint, MagicMock(), MagicMock()).sort_mode == "desc"

    @parameterized.expand(
        [
            ("partitioned", "journal_entries", ["created_at"]),
            ("unpartitioned", "chart_of_accounts", None),
        ]
    )
    def test_partitioning(self, _name: str, endpoint: str, expected_keys: list[str] | None) -> None:
        response = campfire_source("key", endpoint, MagicMock(), MagicMock())
        assert response.partition_keys == expected_keys
        assert response.partition_mode == ("datetime" if expected_keys else None)


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(campfire, "make_tracked_session", return_value=session):
            assert validate_credentials("cf_test_key") is expected

    def test_network_error_is_not_valid(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch.object(campfire, "make_tracked_session", return_value=session):
            assert validate_credentials("cf_test_key") is False

    def test_schema_probe_targets_the_given_path(self) -> None:
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response
        with patch.object(campfire, "make_tracked_session", return_value=session):
            validate_credentials("cf_test_key", path="/rr/api/v1/contracts")
        assert session.get.call_args[0][0].startswith(f"{CAMPFIRE_BASE_URL}/rr/api/v1/contracts?")
