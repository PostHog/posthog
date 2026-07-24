import json
from datetime import date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.stockdata import stockdata
from products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.settings import STOCKDATA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.stockdata import (
    StockDataResumeConfig,
    _format_date,
    _format_datetime,
    stockdata_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the stockdata module.
STOCKDATA_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.stockdata.make_tracked_session"
)


def _news_page(data: list[dict[str, Any]], *, found: int, limit: int, page: int) -> Response:
    return _response({"meta": {"found": found, "returned": len(data), "limit": limit, "page": page}, "data": data})


def _data_page(data: Any, *, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {"meta": {}}
    if not drop_data:
        body["data"] = data
    return _response(body)


def _response(body: Any, *, status: int = 200, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.stockdata.org/v1/news/all?api_token=supersecret&page=1"
    return resp


def _make_manager(resume_state: StockDataResumeConfig | None = None) -> mock.MagicMock:
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
    endpoint: str = "news",
    manager: mock.MagicMock | None = None,
    *,
    symbols: str | None = None,
    db_incremental_field_last_value: Any = None,
) -> Any:
    return stockdata_source(
        "supersecret",
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager or _make_manager(),
        symbols=symbols,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


class TestCursorFormatting:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 4, 9, 12, 30), "2021-04-09"),
            ("date", date(2021, 4, 9), "2021-04-09"),
            ("iso_string", "2021-04-09T00:00:00+0000", "2021-04-09"),
        ]
    )
    def test_format_date(self, _name: str, value: Any, expected: str) -> None:
        assert _format_date(value) == expected

    @parameterized.expand(
        [
            ("datetime", datetime(2021, 4, 9, 12, 30, 5), "2021-04-09T12:30:05"),
            ("date", date(2021, 4, 9), "2021-04-09"),
            ("iso_string_with_tz", "2021-04-09T12:30:05.123456Z", "2021-04-09T12:30:05"),
        ]
    )
    def test_format_datetime(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestNewsPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_found_reached(self, MockSession) -> None:
        session = MockSession.return_value
        page1 = [{"uuid": f"u{i}"} for i in range(100)]
        page2 = [{"uuid": f"u{i}"} for i in range(100, 150)]
        params = _wire(
            session,
            [_news_page(page1, found=150, limit=100, page=1), _news_page(page2, found=150, limit=100, page=2)],
        )

        rows = _rows(_source("news"))

        assert len(rows) == 150
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_at_20k_result_cap(self, MockSession) -> None:
        # limit × page can't exceed 20,000; requesting past it errors, so pagination must stop there.
        session = MockSession.return_value
        page1 = [{"uuid": f"u{i}"} for i in range(3)]
        page2 = [{"uuid": f"v{i}"} for i in range(3)]
        _wire(
            session,
            [
                _news_page(page1, found=50_000, limit=10_000, page=1),
                _news_page(page2, found=50_000, limit=10_000, page=2),
            ],
        )

        rows = _rows(_source("news"))

        assert len(rows) == 6
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_first_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_news_page([], found=0, limit=100, page=1)])

        assert _rows(_source("news")) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_news_page([{"uuid": "u1"}], found=1, limit=100, page=3)])

        _rows(_source("news", manager=_make_manager(StockDataResumeConfig(next_page=3))))

        # The first request must start from the persisted page, not page 1.
        assert params[0]["page"] == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding_a_page(self, MockSession) -> None:
        session = MockSession.return_value
        page1 = [{"uuid": f"u{i}"} for i in range(100)]
        page2 = [{"uuid": f"u{i}"} for i in range(100, 200)]
        _wire(
            session,
            [_news_page(page1, found=200, limit=100, page=1), _news_page(page2, found=200, limit=100, page=2)],
        )

        manager = _make_manager()
        _rows(_source("news", manager=manager))

        # State saved once, with the next page to resume from, only while more pages remain.
        manager.save_state.assert_called_once_with(StockDataResumeConfig(next_page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_data_page(None, drop_data=True)])

        # A 200 body without "data" (an error envelope or changed shape) fails loud rather than
        # silently syncing 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("news"))


class TestRequestParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_news_sorts_by_published_on_and_omits_symbols_by_default(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_news_page([{"uuid": "u1"}], found=1, limit=100, page=1)])

        _rows(_source("news", symbols=None))

        assert params[0]["sort"] == "published_on"
        assert "symbols" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_news_filters_by_normalized_symbols_when_configured(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_news_page([{"uuid": "u1"}], found=1, limit=100, page=1)])

        _rows(_source("news", symbols=" aapl, msft ,"))

        assert params[0]["symbols"] == "AAPL,MSFT"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_news_incremental_passes_published_after_watermark(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_news_page([{"uuid": "u1"}], found=1, limit=100, page=1)])

        _rows(_source("news", db_incremental_field_last_value=datetime(2021, 4, 9, 12, 30, 5)))

        assert params[0]["published_after"] == "2021-04-09T12:30:05"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_eod_requests_ascending_day_interval_with_date_from_watermark(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_data_page([{"ticker": "AAPL", "date": "2021-04-09", "data": {}}])])

        _rows(_source("eod", symbols="AAPL", db_incremental_field_last_value="2021-04-09T00:00:00+0000"))

        assert params[0]["sort"] == "asc"
        assert params[0]["interval"] == "day"
        assert params[0]["symbols"] == "AAPL"
        assert params[0]["date_from"] == "2021-04-09"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_intraday_uses_hour_interval(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_data_page([])])

        _rows(_source("intraday", symbols="AAPL"))

        assert params[0]["interval"] == "hour"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_watermark_params_on_first_incremental_sync(self, MockSession) -> None:
        # A first incremental sync has no stored watermark, so no server-side filter should be sent.
        session = MockSession.return_value
        params = _wire(session, [_data_page([])])

        _rows(_source("eod", symbols="AAPL", db_incremental_field_last_value=None))

        assert "date_from" not in params[0]


class TestRequiresSymbols:
    @parameterized.expand([("quote",), ("eod",), ("intraday",), ("dividends",), ("splits",)])
    def test_price_endpoints_require_symbols(self, endpoint: str) -> None:
        # Selecting a price table with no symbols is a permanent misconfiguration.
        with pytest.raises(ValueError) as exc:
            _source(endpoint, symbols=None)
        assert "[missing_symbols]" in str(exc.value)

    def test_blank_symbols_treated_as_missing(self) -> None:
        with pytest.raises(ValueError) as exc:
            _source("eod", symbols=" , ")
        assert "[missing_symbols]" in str(exc.value)


class TestRowShapes:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_eod_rows_flatten_nested_ohlcv(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _data_page(
                    [
                        {
                            "ticker": "AAPL",
                            "date": "2021-04-09T00:00:00.000000Z",
                            "data": {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100},
                        }
                    ]
                )
            ],
        )

        rows = _rows(_source("eod", symbols="AAPL"))

        assert rows == [
            {
                "ticker": "AAPL",
                "date": "2021-04-09T00:00:00.000000Z",
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
            }
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_data_object_yields_no_rows(self, MockSession) -> None:
        # StockData.org signals an empty result set as `"data": {}` — it must not become a junk row.
        session = MockSession.return_value
        _wire(session, [_data_page({})])

        assert _rows(_source("quote", symbols="AAPL")) == []


class TestHttpErrors:
    @parameterized.expand(
        [
            ("unauthorized", 401, "Unauthorized"),
            ("payment_required", 402, "Payment Required"),
            ("forbidden", 403, "Forbidden"),
        ]
    )
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_permanent_status_raises_without_leaking_token(
        self, _name: str, status: int, reason: str, MockSession, _sleep
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": {"code": "x"}}, status=status, reason=reason)])

        with pytest.raises(requests.HTTPError) as exc:
            _rows(_source("news"))

        # The api_token rides in the query string, so it must be redacted out of the error message
        # that becomes the user-visible `latest_error`.
        assert str(status) in str(exc.value)
        assert "supersecret" not in str(exc.value)
        # Permanent credential/plan/quota problem — not retried.
        assert session.send.call_count == 1


class TestSourceResponse:
    @parameterized.expand(
        [
            ("news", ["uuid"], "published_at", "desc"),
            ("quote", ["ticker"], None, "asc"),
            ("eod", ["ticker", "date"], "date", "asc"),
            ("intraday", ["ticker", "date"], "date", "asc"),
            ("dividends", ["ticker", "date"], "date", "asc"),
            ("splits", ["ticker", "date"], "date", "asc"),
        ]
    )
    def test_source_response_keys_partitioning_and_sort(
        self, endpoint: str, expected_keys: list[str], expected_partition: str | None, expected_sort: str
    ) -> None:
        response = _source(endpoint, symbols="AAPL")
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == expected_sort
        if expected_partition is None:
            assert response.partition_keys is None
        else:
            assert response.partition_keys == [expected_partition]
            assert response.partition_mode == "datetime"

    def test_every_endpoint_builds_a_source_response(self) -> None:
        for endpoint in STOCKDATA_ENDPOINTS:
            response = _source(endpoint, symbols="AAPL")
            assert response.name == endpoint
            assert callable(response.items)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("quota_exhausted_token_still_genuine", 402, True),
            ("unauthorized", 401, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status
        session = mock.MagicMock()
        session.get.return_value = response
        with mock.patch(STOCKDATA_SESSION_PATCH, return_value=session):
            ok, message = validate_credentials("k")
        assert ok is expected
        if expected:
            assert message is None
        else:
            assert message

    def test_handles_network_error(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(STOCKDATA_SESSION_PATCH, return_value=session):
            ok, message = validate_credentials("k")
        assert ok is False
        assert message


def test_module_exposes_base_url() -> None:
    assert stockdata.STOCKDATA_BASE_URL == "https://api.stockdata.org/v1"
