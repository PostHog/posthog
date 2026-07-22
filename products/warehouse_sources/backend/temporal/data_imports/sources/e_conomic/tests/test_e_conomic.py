import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic import (
    E_CONOMIC_BASE_URL,
    EConomicResumeConfig,
    _assert_trusted_url,
    _format_incremental_value,
    e_conomic_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.settings import (
    E_CONOMIC_ENDPOINTS,
    ENDPOINTS,
)

# The rest_source client builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the e_conomic module.
E_CONOMIC_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic.make_tracked_session"
)
# tenacity naps via time.sleep; patch it so retry tests don't pay real backoff.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(
    collection: list[dict[str, Any]] | None,
    *,
    next_page: str | None = None,
    status_code: int = 200,
    drop_collection: bool = False,
    location: str | None = None,
) -> Response:
    body: dict[str, Any] = {"pagination": {}}
    if next_page is not None:
        body["pagination"]["nextPage"] = next_page
    if not drop_collection:
        body["collection"] = collection or []
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    if location is not None:
        resp.headers["Location"] = location
    return resp


def _make_manager(resume: EConomicResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run shows
    only the final state — snapshot a copy when each request is prepared instead. The returned prepared
    object carries a real ``url`` string so the client's allowed-host check can parse it.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        prepared = mock.MagicMock()
        prepared.url = request.url
        prepared.is_redirect = getattr(request, "_is_redirect", False)
        return prepared

    def _send(prepared: Any, **_kwargs: Any) -> Response:
        response = responses[_send.call_index]  # type: ignore[attr-defined]
        _send.call_index += 1  # type: ignore[attr-defined]
        # Mirror the real redirect flag onto the prepared object the paginator/client inspects.
        prepared.is_redirect = response.is_redirect
        return response

    _send.call_index = 0  # type: ignore[attr-defined]
    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return e_conomic_source("app", "grant", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


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


class TestAssertTrustedUrl:
    def test_on_host_https_is_allowed(self) -> None:
        _assert_trusted_url("https://restapi.e-conomic.com/customers?skippages=1")

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/customers"),
            ("subdomain_spoof", "https://restapi.e-conomic.com.evil.example.com/customers"),
            ("http_scheme", "http://restapi.e-conomic.com/customers"),
            ("no_scheme", "//restapi.e-conomic.com/customers"),
        ]
    )
    def test_untrusted_url_raises(self, _name: str, url: str) -> None:
        with pytest.raises(ValueError):
            _assert_trusted_url(url)


class TestFirstRequestParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_sends_pagesize_and_sort_no_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"customerGroupNumber": 1}])])

        _rows(_source("customer_groups", _make_manager()))

        assert params[0]["params"]["pagesize"] == 1000
        assert params[0]["params"]["sort"] == "customerGroupNumber"
        assert "filter" not in params[0]["params"]
        # The first request targets the endpoint path on the API host.
        assert params[0]["url"] == f"{E_CONOMIC_BASE_URL}/customer-groups"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_endpoint_without_sort_omits_sort_param(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"paymentTermsNumber": 1}])])

        _rows(_source("payment_terms", _make_manager()))
        assert "sort" not in params[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_datetime_builds_gte_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"customerNumber": 1}])])

        _rows(
            _source(
                "customers",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                incremental_field="lastUpdated",
            )
        )
        assert params[0]["params"]["filter"] == "lastUpdated$gte:2026-01-02T03:04:05Z"
        assert params[0]["params"]["sort"] == "lastUpdated"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_integer_builds_gte_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"bookedInvoiceNumber": 1}])])

        _rows(
            _source(
                "invoices_booked",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=1052,
                incremental_field="bookedInvoiceNumber",
            )
        )
        assert params[0]["params"]["filter"] == "bookedInvoiceNumber$gte:1052"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_without_last_value_omits_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"customerNumber": 1}])])

        _rows(
            _source(
                "customers",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
                incremental_field="lastUpdated",
            )
        )
        assert "filter" not in params[0]["params"]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_page_links_until_absent(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        next_url = f"{E_CONOMIC_BASE_URL}/customers?skippages=1"
        _wire(
            session,
            [
                _response([{"customerNumber": 1}], next_page=next_url),
                _response([{"customerNumber": 2}]),
            ],
        )

        rows = _rows(_source("customers", _make_manager()))
        assert [r["customerNumber"] for r in rows] == [1, 2]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding_each_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        next_url = f"{E_CONOMIC_BASE_URL}/customers?skippages=1"
        _wire(
            session,
            [
                _response([{"customerNumber": 1}], next_page=next_url),
                _response([{"customerNumber": 2}]),
            ],
        )
        manager = _make_manager()

        _rows(_source("customers", manager))

        # State is saved once (only when a next page exists) and points at the not-yet-fetched page.
        manager.save_state.assert_called_once_with(EConomicResumeConfig(next_url=next_url))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_saves_no_state(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"customerNumber": 1}])])
        manager = _make_manager()

        _rows(_source("customers", manager))
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        resume_url = f"{E_CONOMIC_BASE_URL}/customers?skippages=5"
        params = _wire(session, [_response([{"customerNumber": 99}])])

        _rows(_source("customers", _make_manager(EConomicResumeConfig(next_url=resume_url))))

        # First (and only) fetch starts at the resumed URL, not the endpoint's first page.
        assert params[0]["url"] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_collection_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])
        assert _rows(_source("customers", _make_manager())) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_collection_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        # A body without `collection` is a legitimate zero-row page, not a fail-loud condition.
        session = MockSession.return_value
        _wire(session, [_response(None, drop_collection=True)])
        assert _rows(_source("customers", _make_manager())) == []


class TestErrorHandling:
    @parameterized.expand([("server_error", 500), ("bad_gateway", 503), ("throttled", 429)])
    @mock.patch(CLIENT_SESSION_PATCH)
    @mock.patch(SLEEP_PATCH)
    def test_retryable_status_is_retried(
        self, _name: str, status_code: int, _sleep: mock.MagicMock, MockSession: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, status_code=status_code), _response([{"customerNumber": 7}])])

        rows = _rows(_source("customers", _make_manager()))
        assert [r["customerNumber"] for r in rows] == [7]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    @mock.patch(SLEEP_PATCH)
    def test_client_error_raises_http_error(
        self, _name: str, status_code: int, _sleep: mock.MagicMock, MockSession: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, status_code=status_code)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("customers", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_redirect_is_rejected(self, MockSession: mock.MagicMock) -> None:
        # Redirects are disabled so a bounce can't carry the auth headers to another host.
        session = MockSession.return_value
        _wire(session, [_response(None, status_code=302, location="https://evil.example.com/")])

        with pytest.raises(ValueError):
            _rows(_source("customers", _make_manager()))

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/customers"),
            ("subdomain_spoof", "https://restapi.e-conomic.com.evil.example.com/customers"),
            ("http_scheme", "http://restapi.e-conomic.com/customers"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_next_page_link_is_rejected(
        self, _name: str, bad_next_page: str, MockSession: mock.MagicMock
    ) -> None:
        # A `nextPage` link pointing off-host or over plain http must abort before it is fetched.
        session = MockSession.return_value
        _wire(session, [_response([{"customerNumber": 1}], next_page=bad_next_page)])

        with pytest.raises(ValueError):
            _rows(_source("customers", _make_manager()))
        # Only the first (valid) request was sent; the bad link was never fetched.
        assert session.send.call_count == 1


class TestSourceResponse:
    @parameterized.expand(sorted(ENDPOINTS))
    def test_primary_keys_and_sort_mode(self, endpoint: str) -> None:
        config = E_CONOMIC_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())
        assert response.primary_keys == config.primary_keys
        # Only sortable endpoints advertise ascending order; unsortable ones (e.g. payment_terms) don't.
        assert response.sort_mode == ("asc" if config.sort else None)

    def test_booked_invoices_partition_on_stable_date(self) -> None:
        response = _source("invoices_booked", _make_manager())
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date"]
        assert response.partition_format == "month"

    def test_non_partitioned_endpoint_has_no_partitioning(self) -> None:
        response = _source("customers", _make_manager())
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("server_error", 500, False)])
    @mock.patch(E_CONOMIC_SESSION_PATCH)
    def test_status_code_maps_to_bool(
        self, _name: str, status_code: int, expected: bool, mock_session: mock.MagicMock
    ) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        mock_session.return_value = session
        assert validate_credentials("app", "grant") is expected

    @mock.patch(E_CONOMIC_SESSION_PATCH)
    def test_request_exception_is_false(self, mock_session: mock.MagicMock) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError()
        mock_session.return_value = session
        assert validate_credentials("app", "grant") is False

    @mock.patch(E_CONOMIC_SESSION_PATCH)
    def test_probe_does_not_follow_redirects(self, mock_session: mock.MagicMock) -> None:
        # Credentials ride in X-AppSecretToken / X-AgreementGrantToken headers, which requests does
        # not strip on a cross-origin redirect — so the probe must not follow one and replay them.
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        mock_session.return_value = session

        validate_credentials("app", "grant")

        assert session.get.call_args.kwargs["allow_redirects"] is False
