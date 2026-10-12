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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.marketstack import (
    MarketstackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.marketstack import (
    MARKETSTACK_API_VERSION_V1,
    MARKETSTACK_API_VERSION_V2,
    MarketstackResumeConfig,
    _format_date,
    marketstack_base_url,
    marketstack_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.source import MarketstackSource

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
    api_version: str = MARKETSTACK_API_VERSION_V2,
) -> Any:
    return marketstack_source(
        "supersecret",
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager or _make_manager(),
        api_version=api_version,
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
    def test_missing_data_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page(None, drop_data=True)])

        # A 200 body without "data" (an unrecognized error envelope or changed shape) fails loud
        # rather than silently syncing 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("currencies", symbols=None))


class TestRequiresSymbols:
    @parameterized.expand(
        [
            ("eod", "[missing_symbols]"),
            ("intraday", "[missing_symbols]"),
            ("splits", "[missing_symbols]"),
            ("dividends", "[missing_symbols]"),
            ("tickerinfo", "[missing_symbols]"),
            ("companyratings", "[missing_symbols]"),
            ("submissions", "[missing_cik_codes]"),
        ]
    )
    def test_endpoints_require_their_lookup_values(self, endpoint: str, expected_code: str) -> None:
        # Selecting a table with nothing to look up is a permanent misconfiguration.
        with pytest.raises(ValueError) as exc:
            _source(endpoint, symbols=None)
        assert expected_code in str(exc.value)

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
            assert validate_credentials("k", MARKETSTACK_API_VERSION_V2) is expected

    def test_handles_network_error(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(MARKETSTACK_SESSION_PATCH, return_value=session):
            assert validate_credentials("k", MARKETSTACK_API_VERSION_V2) is False

    @parameterized.expand(
        [
            (MARKETSTACK_API_VERSION_V1, "https://api.marketstack.com/v1/exchanges"),
            (MARKETSTACK_API_VERSION_V2, "https://api.marketstack.com/v2/exchanges"),
        ]
    )
    def test_probe_url_matches_pinned_version(self, version: str, expected_url: str) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": []}
        session = mock.MagicMock()
        session.get.return_value = response
        with mock.patch(MARKETSTACK_SESSION_PATCH, return_value=session):
            validate_credentials("k", version)
        assert session.get.call_args.args[0] == expected_url


class TestBaseUrl:
    @parameterized.expand(
        [
            (MARKETSTACK_API_VERSION_V1, "https://api.marketstack.com/v1"),
            (MARKETSTACK_API_VERSION_V2, "https://api.marketstack.com/v2"),
        ]
    )
    def test_base_url_per_supported_version(self, version: str, expected: str) -> None:
        assert marketstack_base_url(version) == expected

    def test_unknown_version_raises(self) -> None:
        # A pin with no mapped base URL must fail loud rather than silently drop the version segment.
        with pytest.raises(ValueError, match="Unsupported Marketstack API version"):
            marketstack_base_url("v3")

    @parameterized.expand([(MARKETSTACK_API_VERSION_V1,), (MARKETSTACK_API_VERSION_V2,)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_request_hits_pinned_version_host(self, version: str, MockSession) -> None:
        session = MockSession.return_value
        session.headers = {}
        sent_urls: list[str] = []

        def _prepare(request: Any) -> mock.MagicMock:
            sent_urls.append(request.url)
            return mock.MagicMock()

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_page([{"code": "USD"}], total=None)]

        _rows(_source("currencies", symbols=None, api_version=version))

        assert sent_urls[0].startswith(f"https://api.marketstack.com/{version}/")


def _fan_out_driver(symbols: str | None = "AAPL", cik_codes: str | None = None) -> SourceDriver:
    return SourceDriver(
        MarketstackSource(), MarketstackSourceConfig(access_key="supersecret", symbols=symbols, cik_codes=cik_codes)
    )


class TestFanOutEndpoints:
    @parameterized.expand(
        [
            (
                "tickerinfo_one_row_per_symbol",
                "tickerinfo",
                {"data": {"name": "Apple Inc", "sector": "Technology", "key_executives": [{"name": "A"}]}},
                [{"ticker": "AAPL", "name": "Apple Inc", "sector": "Technology", "key_executives": [{"name": "A"}]}],
            ),
            (
                "companyratings_flattens_rating",
                "companyratings",
                {
                    "status": {"code": 200, "message": "ok"},
                    "result": {
                        "basics": {"company_name": "Apple Inc", "ticker": "AAPL"},
                        "output": {
                            "analyst_consensus": {"consensus_conclusion": "Buy"},
                            "analysts": [
                                {
                                    "analyst_name": "Jane Doe",
                                    "analyst_firm": "Example Securities",
                                    "analyst_role": "Analyst",
                                    "rating": {"date_rating": "2026-09-01", "price_target": "250", "rated": "buy"},
                                },
                                {"analyst_name": "John Roe", "analyst_firm": "Sample Capital", "rating": None},
                            ],
                        },
                    },
                },
                [
                    {
                        "ticker": "AAPL",
                        "company_name": "Apple Inc",
                        "analyst_name": "Jane Doe",
                        "analyst_firm": "Example Securities",
                        "analyst_role": "Analyst",
                        "date_rating": "2026-09-01",
                        "price_target": "250",
                        "rated": "buy",
                    },
                    {
                        "ticker": "AAPL",
                        "company_name": "Apple Inc",
                        "analyst_name": "John Roe",
                        "analyst_firm": "Sample Capital",
                    },
                ],
            ),
            (
                "companyratings_without_analysts_yields_nothing",
                "companyratings",
                {"result": {"basics": {"ticker": "AAPL"}, "output": {"analysts": None}}},
                [],
            ),
            (
                "submissions_transposes_filing_arrays",
                "submissions",
                {
                    "data": {
                        "cik_code": "0000000001",
                        "company_name": "Example Corp",
                        "tickers": ["EXMP"],
                        "filings": {
                            "recent": {
                                "accession_number": ["0000000001-26-000002", "0000000001-26-000001"],
                                "filing_date": ["2026-08-01", "2026-05-01"],
                                "form": ["10-Q"],
                            },
                            "files": [],
                        },
                    }
                },
                [
                    {
                        "cik_code": "0000000001",
                        "company_name": "Example Corp",
                        "accession_number": "0000000001-26-000002",
                        "filing_date": "2026-08-01",
                        "form": "10-Q",
                    },
                    {
                        "cik_code": "0000000001",
                        "company_name": "Example Corp",
                        "accession_number": "0000000001-26-000001",
                        "filing_date": "2026-05-01",
                        "form": None,
                    },
                ],
            ),
        ]
    )
    def test_row_shaping(self, _name: str, endpoint: str, body: dict[str, Any], expected: list[dict]) -> None:
        result = _fan_out_driver(cik_codes="0000000001").run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.rows == expected
        assert result.paths == [f"/v2/{endpoint}"]

    def test_walks_each_distinct_value_and_saves_state_before_yielding(self) -> None:
        def ratings(ticker: str) -> ScriptedResponse:
            return ScriptedResponse(
                json={
                    "result": {
                        "basics": {"ticker": ticker},
                        "output": {"analysts": [{"analyst_name": "Jane Doe", "rating": {"date_rating": "2026-09-01"}}]},
                    }
                }
            )

        result = _fan_out_driver(symbols=" AAPL, MSFT,AAPL,").run("companyratings", [ratings("AAPL"), ratings("MSFT")])

        assert result.raised is None
        assert result.params("ticker") == ["AAPL", "MSFT"]
        assert [row["ticker"] for row in result.rows] == ["AAPL", "MSFT"]
        assert result.committed_states == [MarketstackResumeConfig(next_offset=1)]

    def test_resumes_from_the_next_value(self) -> None:
        result = _fan_out_driver(symbols="AAPL,MSFT").run(
            "tickerinfo",
            [ScriptedResponse(json={"data": {"ticker": "MSFT"}})],
            resume_state=MarketstackResumeConfig(next_offset=1),
        )

        assert result.raised is None
        assert result.params("ticker") == ["MSFT"]

    def test_error_envelope_fails_loud(self) -> None:
        result = _fan_out_driver().run(
            "tickerinfo",
            [ScriptedResponse(json={"error": {"code": "function_access_restricted", "message": "Upgrade your plan."}})],
        )

        assert isinstance(result.raised, ValueError)
        assert "[function_access_restricted]" in str(result.raised)
        assert "supersecret" not in str(result.raised)
