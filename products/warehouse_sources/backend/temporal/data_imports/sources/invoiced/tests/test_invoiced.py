import json
from base64 import b64encode
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import PreparedRequest, Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.invoiced.invoiced import (
    INVOICED_BASE_URL,
    PAGE_SIZE,
    InvoicedResumeConfig,
    InvoicedUntrustedURLError,
    _to_unix_timestamp,
    _validate_pagination_url,
    invoiced_source,
    validate_credentials,
)

# The framework's RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the invoiced module.
INVOICED_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.invoiced.invoiced.make_tracked_session"
)


def _response(items: Any, next_url: str | None = None, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(items).encode()
    if next_url:
        # requests parses `response.links` from the Link header; HeaderLinkPaginator reads rel="next".
        resp.headers["Link"] = f'<{next_url}>; rel="next"'
    return resp


def _make_manager(resume_state: InvoicedResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run shows
    only the final state — snapshot it when each request is prepared. Preparing the request for real
    also applies the framework auth (so the Authorization header can be asserted) and builds a real
    ``prepared.url`` for the client's SSRF host check.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Request) -> PreparedRequest:
        prepared = request.prepare()
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "prepared": prepared})
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[list[dict[str, Any]]]:
    return list(source_response.items())


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


class TestSourcePagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_link_header_and_saves_state_after_yield(self, MockSession) -> None:
        session = MockSession.return_value
        page_two_url = f"{INVOICED_BASE_URL}/customers?page=2&per_page={PAGE_SIZE}"
        snapshots = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}], next_url=page_two_url),
                _response([{"id": 3}]),
            ],
        )

        manager = _make_manager()
        batches = _rows(
            invoiced_source("api-key", "customers", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        assert batches == [[{"id": 1}, {"id": 2}], [{"id": 3}]]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_url == page_two_url
        # The second request follows the Link rel="next" URL verbatim.
        assert snapshots[1]["url"] == page_two_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_request_includes_updated_after_and_sort(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([])])

        _rows(
            invoiced_source(
                "api-key",
                "invoices",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
            )
        )

        params = snapshots[0]["params"]
        assert params["updated_after"] == 1700000000
        assert params["sort"] == "updated_at asc"
        assert params["per_page"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_omits_updated_after(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([])])

        _rows(invoiced_source("api-key", "customers", team_id=1, job_id="j", resumable_source_manager=_make_manager()))

        assert "updated_after" not in snapshots[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        saved_url = f"{INVOICED_BASE_URL}/customers?page=7&per_page={PAGE_SIZE}"
        snapshots = _wire(session, [_response([])])

        manager = _make_manager(InvoicedResumeConfig(next_url=saved_url))
        _rows(invoiced_source("api-key", "customers", team_id=1, job_id="j", resumable_source_manager=manager))

        assert snapshots[0]["url"] == saved_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_stops_without_saving_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        batches = _rows(
            invoiced_source("api-key", "customers", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_authenticates_with_api_key_as_basic_auth_username(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([])])

        _rows(invoiced_source("api-key", "customers", team_id=1, job_id="j", resumable_source_manager=_make_manager()))

        # HTTP Basic with the API key as username and a blank password: base64("api-key:").
        expected = "Basic " + b64encode(b"api-key:").decode()
        assert snapshots[0]["prepared"].headers["Authorization"] == expected

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_fails_loud(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "boom"})])

        # List endpoints return a top-level array; a non-list body means the shape changed.
        with pytest.raises(ValueError, match="list response body"):
            _rows(
                invoiced_source("api-key", "customers", team_id=1, job_id="j", resumable_source_manager=_make_manager())
            )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_hostile_upstream_next_url_is_rejected(self, MockSession) -> None:
        # An upstream Link header pointing at another host must abort before the API key is sent
        # there, and the poisoned URL must not be persisted as resume state.
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], next_url="https://evil.example.com/customers")])

        manager = _make_manager()
        with pytest.raises(InvoicedUntrustedURLError):
            _rows(invoiced_source("api-key", "customers", team_id=1, job_id="j", resumable_source_manager=manager))
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_hostile_resumed_next_url_is_rejected(self, MockSession) -> None:
        # A poisoned resume state from Redis must never be requested with the API key.
        session = MockSession.return_value
        _wire(session, [])

        manager = _make_manager(InvoicedResumeConfig(next_url="https://evil.example.com/customers"))
        with pytest.raises(InvoicedUntrustedURLError):
            _rows(invoiced_source("api-key", "customers", team_id=1, job_id="j", resumable_source_manager=manager))
        session.send.assert_not_called()


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
    @mock.patch(INVOICED_SESSION_PATCH)
    def test_auth_failure_maps_to_invalid_key(self, _name: str, status_code: int, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("bad-key") == (False, "Invalid Invoiced API key")

    @mock.patch(INVOICED_SESSION_PATCH)
    def test_valid_key(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("good-key") == (True, None)

    @mock.patch(INVOICED_SESSION_PATCH)
    def test_unexpected_status_returns_message(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=500)
        ok, message = validate_credentials("key")
        assert ok is False
        assert message == "Invoiced returned HTTP 500"

    @mock.patch(INVOICED_SESSION_PATCH)
    def test_connection_error_returns_message(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        ok, message = validate_credentials("key")
        assert ok is False
        assert message is not None and "Could not connect to Invoiced" in message


class TestInvoicedSourceResponse:
    def test_response_metadata(self) -> None:
        response = invoiced_source(
            "api-key", "invoices", team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )

        assert response.name == "invoices"
        assert response.primary_keys == ["id"]
        # Rows are requested with an explicit ascending updated_at sort.
        assert response.sort_mode == "asc"
