import json
from datetime import datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack import marketstack
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.marketstack import (
    MarketstackResumeConfig,
    _format_date,
    marketstack_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.settings import MARKETSTACK_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the marketstack module.
MARKETSTACK_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.marketstack.make_tracked_session"
)


def _page(data: list[dict[str, Any]] | None, *, total: int | None = None, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {"pagination": {"limit": 1000, "offset": 0, "count": len(data or []), "total": total}}
    if not drop_data:
        body["data"] = data or []
    return _response(body)


def _error_body(code: str) -> Response:
    # Marketstack signals API-level errors with an HTTP 200 body envelope.
    return _response({"error": {"code": code, "message": "boom"}})


def _response(body: Any, *, status: int = 200, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.marketstack.com/v1/eod?access_key=supersecret&symbols=AAPL&offset=0&limit=1000"
    return resp


def _make_manager(resume_state: MarketstackResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(
    endpoint: str = "eod",
    manager: mock.MagicMock | None = None,
    *,
    symbols: str | None = "AAPL",
    db_incremental_field_last_value: Any = None,
) -> Any:
    return marketstack_source(
        "supersecret",
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager or _make_manager(),
        symbols=symbols,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


class TestFormatDate:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 4, 9, 12, 30), "2021-04-09"),
            ("iso_string", "2021-04-09T00:00:00+0000", "2021-04-09"),
            ("date_string", "2020-08-31", "2020-08-31"),
        ]
    )
    def test_formats_to_yyyy_mm_dd(self, _name: str, value: Any, expected: str) -> None:
        assert _format_date(value) == expected


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_total_reached(self, MockSession) -> None:
        session = MockSession.return_value
        page1 = [{"symbol": "AAPL", "date": f"d{i}"} for i in range(1000)]
        page2 = [{"symbol": "AAPL", "date": f"d{i}"} for i in range(1000, 2000)]
        params = _wire(session, [_page(page1, total=2000), _page(page2, total=2000)])

        rows = _rows(_source())

        assert len(rows) == 2000
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == 1000
        assert params[1]["offset"] == 1000
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_short_page(self, MockSession) -> None:
        # A page shorter than the limit means there's no further page, even without a total.
        session = MockSession.return_value
        _wire(session, [_page([{"code": "USD"}], total=None)])

        rows = _rows(_source("currencies", symbols=None))

        assert [r["code"] for r in rows] == ["USD"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_first_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], total=0)])

        rows = _rows(_source("currencies", symbols=None))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"code": "USD"}], total=None)])

        _rows(_source("currencies", manager=_make_manager(MarketstackResumeConfig(next_offset=2000)), symbols=None))

        # The first (and only) request must start from the persisted offset, not 0.
        assert params[0]["offset"] == 2000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding_a_page(self, MockSession) -> None:
        session = MockSession.return_value
        page1 = [{"code": f"c{i}"} for i in range(1000)]
        page2 = [{"code": f"c{i}"} for i in range(1000, 2000)]
        _wire(session, [_page(page1, total=2000), _page(page2, total=2000)])

        manager = _make_manager()
        _rows(_source("currencies", manager=manager, symbols=None))

        # State saved once, with the next offset to resume from, only while more pages remain.
        manager.save_state.assert_called_once_with(MarketstackResumeConfig(next_offset=1000))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_saves_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"code": "USD"}], total=None)])

        manager = _make_manager()
        _rows(_source("currencies", manager=manager, symbols=None))

        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page(None, drop_data=True)])

        # A 200 body without "data" (an unrecognized error envelope or changed shape) fails loud
        # rather than silently syncing 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("currencies", symbols=None))


class TestRequestParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_time_series_endpoint_requests_ascending_sort_and_symbols(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"symbol": "AAPL"}], total=None)])

        _rows(_source("eod", symbols="AAPL"))

        assert params[0]["sort"] == "ASC"
        assert params[0]["symbols"] == "AAPL"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reference_endpoint_sends_no_symbols_or_sort(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"code": "USD"}], total=None)])

        _rows(_source("currencies", symbols=None))

        assert "symbols" not in params[0]
        assert "sort" not in params[0]
        assert "date_from" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_passes_date_from_watermark(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"symbol": "AAPL"}], total=None)])

        _rows(_source("eod", symbols="AAPL", db_incremental_field_last_value="2021-04-09T00:00:00+0000"))

        assert params[0]["date_from"] == "2021-04-09"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_date_from_on_first_incremental_sync(self, MockSession) -> None:
        # A first incremental sync has no stored watermark, so no date_from should be sent.
        session = MockSession.return_value
        params = _wire(session, [_page([{"symbol": "AAPL"}], total=None)])

        _rows(_source("eod", symbols="AAPL", db_incremental_field_last_value=None))

        assert "date_from" not in params[0]


class TestRequiresSymbols:
    @parameterized.expand([("eod",), ("intraday",), ("splits",), ("dividends",)])
    def test_time_series_endpoints_require_symbols(self, endpoint: str) -> None:
        # Selecting a time-series table with no symbols is a permanent misconfiguration.
        with pytest.raises(ValueError) as exc:
            _source(endpoint, symbols=None)
        assert "[missing_symbols]" in str(exc.value)

    def test_blank_symbols_treated_as_missing(self) -> None:
        with pytest.raises(ValueError) as exc:
            _source("eod", symbols="   ")
        assert "[missing_symbols]" in str(exc.value)


class TestBodyErrorEnvelope:
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_permanent_body_code_raises_and_hides_secret(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_body("invalid_access_key")])

        with pytest.raises(ValueError) as exc:
            _rows(_source())

        # The stable [code] token is what get_non_retryable_errors matches on.
        assert "[invalid_access_key]" in str(exc.value)
        # The access_key secret value must never leak into the user-visible error.
        assert "supersecret" not in str(exc.value)
        # Permanent: raised on the first response, never retried.
        assert session.send.call_count == 1

    @parameterized.expand([("rate_limit_reached",), ("too_many_requests",)])
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rate_limit_body_code_is_retryable(self, code: str, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.return_value = _error_body(code)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source())
        # Retried up to the client's default attempt cap, then re-raised.
        assert session.send.call_count == 5


class TestHttpErrors:
    @parameterized.expand([("unauthorized", 401, "401"), ("forbidden", 403, "403")])
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_hard_auth_status_raises_without_leaking_secret(
        self, _name: str, status: int, expected: str, MockSession, _sleep
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": [], "pagination": {}}, status=status, reason=expected)])

        with pytest.raises(ValueError) as exc:
            _rows(_source())

        assert expected in str(exc.value)
        assert "supersecret" not in str(exc.value)
        assert "access_key" not in str(exc.value)
        # Permanent credential/plan problem — not retried.
        assert session.send.call_count == 1

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_retries_then_raises(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.return_value = _response({}, status=status, reason="err")

        with pytest.raises(RESTClientRetryableError):
            _rows(_source())
        assert session.send.call_count == 5


class TestSourceResponse:
    @parameterized.expand(
        [
            ("eod", ["symbol", "exchange", "date"], "date"),
            ("intraday", ["symbol", "exchange", "date"], "date"),
            ("splits", ["symbol", "date"], "date"),
            ("dividends", ["symbol", "date"], "date"),
            ("tickers", ["symbol"], None),
            ("exchanges", ["mic"], None),
            ("currencies", ["code"], None),
            ("timezones", ["timezone"], None),
        ]
    )
    def test_source_response_keys_and_partitioning(
        self, endpoint: str, expected_keys: list[str], expected_partition: str | None
    ) -> None:
        response = _source(endpoint, symbols="AAPL")
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"
        if expected_partition is None:
            assert response.partition_keys is None
        else:
            assert response.partition_keys == [expected_partition]
            assert response.partition_mode == "datetime"

    def test_every_endpoint_builds_a_source_response(self) -> None:
        for endpoint in MARKETSTACK_ENDPOINTS:
            response = _source(endpoint, symbols="AAPL")
            assert response.name == endpoint
            assert callable(response.items)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, {"data": []}, True),
            ("unauthorized", 401, {"error": {"code": "invalid_access_key"}}, False),
            ("ok_status_but_error_body", 200, {"error": {"code": "usage_limit_reached"}}, False),
        ]
    )
    def test_status_and_body_mapping(self, _name: str, status: int, body: dict, expected: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status
        response.json.return_value = body
        session = mock.MagicMock()
        session.get.return_value = response
        with mock.patch(MARKETSTACK_SESSION_PATCH, return_value=session):
            assert validate_credentials("k") is expected

    def test_handles_network_error(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(MARKETSTACK_SESSION_PATCH, return_value=session):
            assert validate_credentials("k") is False


def test_module_exposes_base_url() -> None:
    assert marketstack.MARKETSTACK_BASE_URL == "https://api.marketstack.com/v1"
