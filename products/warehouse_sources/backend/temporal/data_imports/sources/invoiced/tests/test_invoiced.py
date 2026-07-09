from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.invoiced.invoiced import (
    INVOICED_BASE_URL,
    PAGE_SIZE,
    InvoicedResumeConfig,
    InvoicedUntrustedURLError,
    _to_unix_timestamp,
    _validate_pagination_url,
    get_rows,
    invoiced_source,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.invoiced.invoiced"


def _make_manager(resume_state: InvoicedResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(items: Any, next_url: str | None = None, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = items
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.links = {"next": {"url": next_url}} if next_url else {}
    return resp


class TestToUnixTimestamp:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), 1704164645),
            ("naive_datetime_assumed_utc", datetime(2024, 1, 2, 3, 4, 5), 1704164645),
            ("date", date(2024, 1, 2), 1704153600),
            ("int", 1700000000, 1700000000),
            ("numeric_string", "1700000000", 1700000000),
        ]
    )
    def test_converts_to_epoch_seconds(self, _name: str, value: Any, expected: int) -> None:
        assert _to_unix_timestamp(value) == expected


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_via_link_header_and_saves_state_after_yield(self, mock_session: mock.MagicMock) -> None:
        page_two_url = f"{INVOICED_BASE_URL}/customers?page=2&per_page={PAGE_SIZE}"
        mock_session.return_value.get.side_effect = [
            _response([{"id": 1}, {"id": 2}], next_url=page_two_url),
            _response([{"id": 3}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("api-key", "customers", mock.MagicMock(), manager))

        assert batches == [[{"id": 1}, {"id": 2}], [{"id": 3}]]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_url == page_two_url
        # The second request follows the Link rel="next" URL verbatim.
        assert mock_session.return_value.get.call_args_list[1].args[0] == page_two_url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_request_includes_updated_after_and_sort(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        list(
            get_rows(
                "api-key",
                "invoices",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        query = parse_qs(urlparse(url).query)
        assert urlparse(url).path == "/invoices"
        assert query["updated_after"] == ["1700000000"]
        assert query["sort"] == ["updated_at asc"]
        assert query["per_page"] == [str(PAGE_SIZE)]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_refresh_omits_updated_after(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        list(get_rows("api-key", "customers", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert "updated_after" not in parse_qs(urlparse(url).query)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_next_url(self, mock_session: mock.MagicMock) -> None:
        saved_url = f"{INVOICED_BASE_URL}/customers?page=7&per_page={PAGE_SIZE}"
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager(InvoicedResumeConfig(next_url=saved_url))
        list(get_rows("api-key", "customers", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args.args[0] == saved_url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_response_stops_without_saving_state(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        batches = list(get_rows("api-key", "customers", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_authenticates_with_api_key_as_basic_auth_username(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response([])

        list(get_rows("api-key", "customers", mock.MagicMock(), _make_manager()))

        assert mock_session.return_value.auth == ("api-key", "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_hostile_upstream_next_url_is_rejected(self, mock_session: mock.MagicMock) -> None:
        # An upstream Link header pointing at another host must abort before the API key is sent
        # there, and the poisoned URL must not be persisted as resume state.
        mock_session.return_value.get.return_value = _response(
            [{"id": 1}], next_url="https://evil.example.com/customers"
        )

        manager = _make_manager()
        with pytest.raises(InvoicedUntrustedURLError):
            list(get_rows("api-key", "customers", mock.MagicMock(), manager))
        manager.save_state.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_hostile_resumed_next_url_is_rejected(self, mock_session: mock.MagicMock) -> None:
        # A poisoned resume state from Redis must never be requested with the API key.
        manager = _make_manager(InvoicedResumeConfig(next_url="https://evil.example.com/customers"))
        with pytest.raises(InvoicedUntrustedURLError):
            list(get_rows("api-key", "customers", mock.MagicMock(), manager))
        mock_session.return_value.get.assert_not_called()


class TestValidatePaginationUrl:
    @parameterized.expand(
        [
            ("first_page", f"{INVOICED_BASE_URL}/customers?per_page=100"),
            ("next_page", f"{INVOICED_BASE_URL}/customers?per_page=100&page=2"),
            ("other_endpoint", f"{INVOICED_BASE_URL}/invoices?page=3"),
        ]
    )
    def test_trusted_urls_pass_through(self, _name: str, url: str) -> None:
        assert _validate_pagination_url(url) == url

    @parameterized.expand(
        [
            ("foreign_host", "https://evil.example.com/customers"),
            ("subdomain_lookalike", "https://api.invoiced.com.evil.example.com/customers"),
            ("http_scheme", "http://api.invoiced.com/customers"),
            ("metadata_endpoint", "http://169.254.169.254/latest/meta-data/"),
        ]
    )
    def test_untrusted_urls_raise(self, _name: str, url: str) -> None:
        with pytest.raises(InvoicedUntrustedURLError):
            _validate_pagination_url(url)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("unauthorized", 401),
            ("forbidden", 403),
        ]
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_auth_failure_maps_to_invalid_key(self, _name: str, status_code: int, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({}, status_code=status_code)
        assert validate_credentials("bad-key") == (False, "Invalid Invoiced API key")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_key(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response([])
        assert validate_credentials("good-key") == (True, None)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_unexpected_status_returns_message(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({}, status_code=500)
        ok, message = validate_credentials("key")
        assert ok is False
        assert message == "Invoiced returned HTTP 500"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_connection_error_returns_message(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        ok, message = validate_credentials("key")
        assert ok is False
        assert message is not None and "Could not connect to Invoiced" in message


class TestInvoicedSourceResponse:
    def test_response_metadata(self) -> None:
        response = invoiced_source("api-key", "invoices", mock.MagicMock(), _make_manager())

        assert response.name == "invoices"
        assert response.primary_keys == ["id"]
        # Rows are requested with an explicit ascending updated_at sort.
        assert response.sort_mode == "asc"
