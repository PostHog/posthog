from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic import (
    E_CONOMIC_BASE_URL,
    EConomicResumeConfig,
    EConomicRetryableError,
    _build_initial_url,
    _fetch_page,
    _format_incremental_value,
    e_conomic_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.settings import (
    E_CONOMIC_ENDPOINTS,
    ENDPOINTS,
)


def _make_manager(resume: EConomicResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _fake_response(status_code: int, body: dict | None = None) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = status_code < 400
    response.text = ""
    response.json.return_value = body or {}

    def _raise() -> None:
        if status_code >= 400:
            raise requests.HTTPError(f"{status_code} Client Error", response=response)

    response.raise_for_status.side_effect = _raise
    return response


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("integer_cursor", 1052, "1052"),
            ("string_passthrough", "abc", "abc"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected

    def test_naive_datetime_no_offset_suffix(self) -> None:
        # A naive cursor is treated as UTC, and must not gain a +00:00 offset the API would reject.
        assert "+00:00" not in _format_incremental_value(datetime(2026, 3, 4, 2, 58, 14))


class TestBuildInitialUrl:
    def test_full_refresh_url_has_pagesize_and_sort_no_filter(self) -> None:
        url = _build_initial_url(E_CONOMIC_ENDPOINTS["customer_groups"], False, None, None)
        assert url.startswith(f"{E_CONOMIC_BASE_URL}/customer-groups?")
        assert "pagesize=1000" in url
        assert "sort=customerGroupNumber" in url
        assert "filter=" not in url

    def test_endpoint_without_sort_omits_sort_param(self) -> None:
        url = _build_initial_url(E_CONOMIC_ENDPOINTS["payment_terms"], False, None, None)
        assert "sort=" not in url

    def test_incremental_datetime_builds_gte_filter(self) -> None:
        url = _build_initial_url(
            E_CONOMIC_ENDPOINTS["customers"], True, datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "lastUpdated"
        )
        # `$` and `:` are percent-encoded by urlencode; the API accepts the encoded form.
        assert "filter=lastUpdated%24gte%3A2026-01-02T03%3A04%3A05Z" in url
        assert "sort=lastUpdated" in url

    def test_incremental_integer_builds_gte_filter(self) -> None:
        url = _build_initial_url(E_CONOMIC_ENDPOINTS["invoices_booked"], True, 1052, "bookedInvoiceNumber")
        assert "filter=bookedInvoiceNumber%24gte%3A1052" in url

    def test_incremental_without_last_value_omits_filter(self) -> None:
        url = _build_initial_url(E_CONOMIC_ENDPOINTS["customers"], True, None, "lastUpdated")
        assert "filter=" not in url


class TestFetchPage:
    @parameterized.expand([("throttled", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_raises_retryable_error(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _fake_response(status_code)
        # Bypass the @retry decorator (tenacity sets `__wrapped__`) so we assert the raise logic without
        # ~15s of real backoff sleeps per case.
        with pytest.raises(EConomicRetryableError):
            _fetch_page.__wrapped__(session, "https://restapi.e-conomic.com/customers", MagicMock())  # type: ignore[attr-defined]

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_error_raises_http_error(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _fake_response(status_code)
        with pytest.raises(requests.HTTPError):
            _fetch_page(session, "https://restapi.e-conomic.com/customers", MagicMock())

    def test_success_returns_json(self) -> None:
        session = MagicMock()
        session.get.return_value = _fake_response(200, {"collection": [{"customerNumber": 1}]})
        assert _fetch_page(session, "https://restapi.e-conomic.com/customers", MagicMock()) == {
            "collection": [{"customerNumber": 1}]
        }

    def test_does_not_follow_redirects(self) -> None:
        # Redirects are disabled so a bounce can't carry the auth headers to another host.
        session = MagicMock()
        session.get.return_value = _fake_response(200, {"collection": []})
        _fetch_page(session, "https://restapi.e-conomic.com/customers", MagicMock())
        assert session.get.call_args.kwargs["allow_redirects"] is False

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/customers"),
            ("subdomain_spoof", "https://restapi.e-conomic.com.evil.example.com/customers"),
            ("http_scheme", "http://restapi.e-conomic.com/customers"),
            ("no_scheme", "//restapi.e-conomic.com/customers"),
        ]
    )
    def test_untrusted_url_raises_without_request(self, _name: str, url: str) -> None:
        # An off-host or non-https URL must abort before any GET that would leak the auth headers.
        session = MagicMock()
        with pytest.raises(ValueError):
            _fetch_page(session, url, MagicMock())
        session.get.assert_not_called()


class TestGetRows:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic.make_tracked_session")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic._fetch_page")
    def test_follows_next_page_links_until_absent(self, mock_fetch: MagicMock, _mock_session: MagicMock) -> None:
        page1 = {
            "collection": [{"customerNumber": 1}],
            "pagination": {"nextPage": "https://restapi.e-conomic.com/customers?skippages=1"},
        }
        page2 = {"collection": [{"customerNumber": 2}], "pagination": {}}
        mock_fetch.side_effect = [page1, page2]

        manager = _make_manager()
        batches = list(get_rows("app", "grant", "customers", MagicMock(), manager))

        assert batches == [[{"customerNumber": 1}], [{"customerNumber": 2}]]
        assert mock_fetch.call_count == 2

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic.make_tracked_session")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic._fetch_page")
    def test_saves_state_after_yielding_each_page(self, mock_fetch: MagicMock, _mock_session: MagicMock) -> None:
        next_url = "https://restapi.e-conomic.com/customers?skippages=1"
        mock_fetch.side_effect = [
            {"collection": [{"customerNumber": 1}], "pagination": {"nextPage": next_url}},
            {"collection": [{"customerNumber": 2}], "pagination": {}},
        ]
        manager = _make_manager()

        list(get_rows("app", "grant", "customers", MagicMock(), manager))

        # State is saved once (only when a next page exists) and points at the not-yet-fetched page.
        manager.save_state.assert_called_once_with(EConomicResumeConfig(next_url=next_url))

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic.make_tracked_session")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic._fetch_page")
    def test_resumes_from_saved_state(self, mock_fetch: MagicMock, _mock_session: MagicMock) -> None:
        resume_url = "https://restapi.e-conomic.com/customers?skippages=5"
        mock_fetch.return_value = {"collection": [{"customerNumber": 99}], "pagination": {}}
        manager = _make_manager(EConomicResumeConfig(next_url=resume_url))

        list(get_rows("app", "grant", "customers", MagicMock(), manager))

        # First (and only) fetch starts at the resumed URL, not the endpoint's first page.
        assert mock_fetch.call_args_list[0].args[1] == resume_url

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic.make_tracked_session")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic._fetch_page")
    def test_empty_collection_yields_nothing(self, mock_fetch: MagicMock, _mock_session: MagicMock) -> None:
        mock_fetch.return_value = {"collection": [], "pagination": {}}
        assert list(get_rows("app", "grant", "customers", MagicMock(), _make_manager())) == []


class TestECONomicSourceResponse:
    @parameterized.expand(sorted(ENDPOINTS))
    def test_primary_keys_match_settings(self, endpoint: str) -> None:
        config = E_CONOMIC_ENDPOINTS[endpoint]
        response = e_conomic_source("app", "grant", endpoint, MagicMock(), _make_manager())
        assert response.primary_keys == config.primary_keys
        # Only sortable endpoints advertise ascending order; unsortable ones (e.g. payment_terms) don't.
        assert response.sort_mode == ("asc" if config.sort else None)

    def test_booked_invoices_partition_on_stable_date(self) -> None:
        response = e_conomic_source("app", "grant", "invoices_booked", MagicMock(), _make_manager())
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date"]
        assert response.partition_format == "month"

    def test_non_partitioned_endpoint_has_no_partitioning(self) -> None:
        response = e_conomic_source("app", "grant", "customers", MagicMock(), _make_manager())
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("server_error", 500, False)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic.make_tracked_session")
    def test_status_code_maps_to_bool(
        self, _name: str, status_code: int, expected: bool, mock_session: MagicMock
    ) -> None:
        session = MagicMock()
        session.get.return_value = _fake_response(status_code)
        mock_session.return_value = session
        assert validate_credentials("app", "grant") is expected

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic.make_tracked_session")
    def test_request_exception_is_false(self, mock_session: MagicMock) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError()
        mock_session.return_value = session
        assert validate_credentials("app", "grant") is False
