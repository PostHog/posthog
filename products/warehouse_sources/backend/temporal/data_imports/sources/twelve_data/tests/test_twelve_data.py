import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import structlog
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_data import twelve_data
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_data.twelve_data import (
    TwelveDataError,
    TwelveDataResumeConfig,
    _format_time_bound,
    parse_symbols,
    twelve_data_rows,
    twelve_data_source,
    validate_credentials,
)

SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.twelve_data.twelve_data.make_tracked_session"
)

LOGGER = structlog.get_logger()


def _response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = "https://api.twelvedata.com/mock"
    resp.reason = "Error" if status >= 400 else "OK"
    resp._content = json.dumps(body).encode()
    return resp


def _error_body(code: int, message: str) -> dict[str, Any]:
    return {"code": code, "message": message, "status": "error"}


def _make_manager(resume_state: TwelveDataResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _time_series_body(symbol: str, datetimes: list[str]) -> dict[str, Any]:
    return {
        "meta": {"symbol": symbol, "interval": "1day"},
        "values": [
            {"datetime": dt, "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "100"}
            for dt in datetimes
        ],
        "status": "ok",
    }


def _run(
    endpoint: str,
    responses: list[Response],
    symbols: list[str] | None = None,
    manager: mock.MagicMock | None = None,
    **kwargs: Any,
) -> tuple[list[list[dict]], mock.MagicMock, mock.MagicMock]:
    manager = manager if manager is not None else _make_manager()
    session = mock.MagicMock()
    session.get.side_effect = responses
    with mock.patch(SESSION_PATCH, return_value=session):
        batches = list(
            twelve_data_rows(
                api_key="key",
                endpoint=endpoint,
                symbols=symbols if symbols is not None else ["AAPL"],
                interval="1day",
                config_start_date=kwargs.pop("config_start_date", None),
                resumable_source_manager=manager,
                logger=LOGGER,
                **kwargs,
            )
        )
    return batches, session, manager


def _params(session: mock.MagicMock, call_index: int) -> dict[str, Any]:
    return session.get.call_args_list[call_index].kwargs["params"]


class TestParseSymbols:
    @parameterized.expand(
        [
            ("simple", "AAPL,MSFT", ["AAPL", "MSFT"]),
            ("whitespace", " AAPL , MSFT ", ["AAPL", "MSFT"]),
            ("blank_entries", "AAPL,,MSFT,", ["AAPL", "MSFT"]),
            ("duplicates", "AAPL,MSFT,AAPL", ["AAPL", "MSFT"]),
            ("forex_pair", "EUR/USD", ["EUR/USD"]),
            ("empty", "  ", []),
        ]
    )
    def test_parse_symbols(self, _name: str, raw: str, expected: list[str]) -> None:
        assert parse_symbols(raw) == expected


class TestFormatTimeBound:
    @parameterized.expand(
        [
            ("datetime", datetime(2026, 7, 1, 15, 30, 0, tzinfo=UTC), "2026-07-01 15:30:00"),
            ("date", date(2026, 7, 1), "2026-07-01"),
            ("string", "2026-07-01", "2026-07-01"),
        ]
    )
    def test_formats_watermark_for_start_date_param(self, _name: str, value: Any, expected: str) -> None:
        assert _format_time_bound(value) == expected


class TestErrorEnvelope:
    @parameterized.expand(
        [
            ("unauthorized", 401, "**apikey** parameter is incorrect"),
            ("forbidden", 403, "available starting with the Grow plan"),
            ("rate_limited", 429, "You have run out of API credits"),
        ]
    )
    def test_error_envelope_raises_with_code(self, _name: str, code: int, message: str) -> None:
        # The API wraps errors in a JSON envelope (sometimes on HTTP 200) — the raised message must
        # carry the vendor code so get_non_retryable_errors / get_retryable_errors can match it.
        responses = [_response(_error_body(code, message))]
        with pytest.raises(TwelveDataError, match=f"Twelve Data API error {code}"):
            _run("quotes", responses)

    def test_no_data_in_window_is_empty_not_error(self) -> None:
        # An incremental sync with no new bars gets a code-400 "error" — it must complete cleanly,
        # not fail the job.
        responses = [
            _response(_error_body(400, "No data is available on the specified dates."), status=400),
        ]
        batches, _session, _manager = _run(
            "time_series", responses, should_use_incremental_field=True, db_incremental_field_last_value="2026-07-21"
        )
        assert batches == []


class TestCatalogEndpoints:
    def test_catalog_rows_unwrapped_from_data_key(self) -> None:
        rows = [{"symbol": "AAPL", "mic_code": "XNGS"}, {"symbol": "AAPL", "mic_code": "XWBO"}]
        batches, session, _ = _run("stocks", [_response({"data": rows, "status": "ok"})])
        assert batches == [rows]
        assert session.get.call_count == 1

    def test_large_catalog_yields_in_chunks(self) -> None:
        rows = [{"symbol": f"S{i}", "mic_code": "X"} for i in range(twelve_data.CATALOG_CHUNK_SIZE + 1)]
        batches, _session, _ = _run("stocks", [_response({"data": rows, "status": "ok"})])
        assert [len(b) for b in batches] == [twelve_data.CATALOG_CHUNK_SIZE, 1]

    def test_catalog_does_not_touch_resume_state(self) -> None:
        _batches, _session, manager = _run("exchanges", [_response({"data": [{"code": "XNGS"}], "status": "ok"})])
        manager.save_state.assert_not_called()


class TestPerSymbolEndpoints:
    def test_rows_carry_symbol_from_meta(self) -> None:
        body = {
            "meta": {"symbol": "AAPL"},
            "dividends": [{"ex_date": "2026-05-11", "amount": 0.27}],
        }
        batches, session, _ = _run("dividends", [_response(body)])
        assert batches == [[{"symbol": "AAPL", "ex_date": "2026-05-11", "amount": 0.27}]]
        assert _params(session, 0)["symbol"] == "AAPL"

    def test_quote_single_object_row_drops_status(self) -> None:
        body = {"symbol": "AAPL", "close": "326.47", "status": "ok"}
        batches, _session, _ = _run("quotes", [_response(body)])
        assert batches == [[{"symbol": "AAPL", "close": "326.47"}]]

    def test_iterates_each_symbol_and_bookmarks_completion(self) -> None:
        responses = [
            _response({"meta": {"symbol": "AAPL"}, "splits": [{"date": "2020-08-31", "ratio": 0.25}]}),
            _response({"meta": {"symbol": "MSFT"}, "splits": []}),
        ]
        batches, session, manager = _run("splits", responses, symbols=["AAPL", "MSFT"])
        assert [_params(session, i)["symbol"] for i in range(2)] == ["AAPL", "MSFT"]
        assert len(batches) == 1
        # A crash between symbols must resume at MSFT, not refetch AAPL.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved[0].completed_symbols == ["AAPL"]
        assert saved[-1].completed_symbols == ["AAPL", "MSFT"]

    def test_sync_rejects_too_many_symbols(self) -> None:
        # The cap must hold at sync time too, so a stored config can't bypass validation.
        symbols = [f"S{i}" for i in range(twelve_data.MAX_SYMBOLS + 1)]
        with pytest.raises(TwelveDataError, match="Twelve Data symbol limit exceeded"):
            _run("quotes", [], symbols=symbols)

    def test_resume_skips_completed_symbols(self) -> None:
        resume = TwelveDataResumeConfig(completed_symbols=["AAPL"])
        responses = [_response({"meta": {"symbol": "MSFT"}, "splits": [{"date": "2003-02-18", "ratio": 0.5}]})]
        batches, session, _ = _run("splits", responses, symbols=["AAPL", "MSFT"], manager=_make_manager(resume))
        assert session.get.call_count == 1
        assert _params(session, 0)["symbol"] == "MSFT"
        assert batches[0][0]["symbol"] == "MSFT"


class TestTimeSeries:
    def test_first_sync_without_start_date_fetches_single_page(self) -> None:
        # Without a lower bound there is nothing to back-walk toward — even a full page must not
        # trigger endless history paging on high-frequency intervals.
        with mock.patch.object(twelve_data, "TIME_SERIES_PAGE_SIZE", 2):
            responses = [_response(_time_series_body("AAPL", ["2026-07-21", "2026-07-20"]))]
            batches, session, _ = _run("time_series", responses)
        assert session.get.call_count == 1
        assert "start_date" not in _params(session, 0)
        assert batches[0][0] == {
            "symbol": "AAPL",
            "interval": "1day",
            "datetime": "2026-07-21",
            "open": "1",
            "high": "2",
            "low": "0.5",
            "close": "1.5",
            "volume": "100",
        }

    def test_incremental_walks_back_to_watermark(self) -> None:
        with mock.patch.object(twelve_data, "TIME_SERIES_PAGE_SIZE", 3):
            responses = [
                _response(_time_series_body("AAPL", ["2026-07-21", "2026-07-20", "2026-07-19"])),
                # end_date is inclusive, so the boundary bar (07-19) comes back and must be deduped;
                # the short page ends the walk.
                _response(_time_series_body("AAPL", ["2026-07-19", "2026-07-18"])),
            ]
            batches, session, manager = _run(
                "time_series",
                responses,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 7, 18),
            )

        assert _params(session, 0)["start_date"] == "2026-07-18"
        assert "end_date" not in _params(session, 0)
        assert _params(session, 1)["start_date"] == "2026-07-18"
        assert _params(session, 1)["end_date"] == "2026-07-19"

        yielded = [(row["datetime"]) for batch in batches for row in batch]
        assert yielded == ["2026-07-21", "2026-07-20", "2026-07-19", "2026-07-18"]

        # Mid-walk checkpoint points at the next page; the final checkpoint completes the symbol.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved[0] == TwelveDataResumeConfig(
            completed_symbols=[], current_symbol="AAPL", next_end_date="2026-07-19"
        )
        assert saved[-1] == TwelveDataResumeConfig(completed_symbols=["AAPL"])

    def test_config_start_date_used_when_not_incremental(self) -> None:
        with mock.patch.object(twelve_data, "TIME_SERIES_PAGE_SIZE", 2):
            responses = [_response(_time_series_body("AAPL", ["2020-01-03", "2020-01-02"]))]
            # Short page → no further requests.
            responses[0]._content = json.dumps(_time_series_body("AAPL", ["2020-01-02"])).encode()
            _batches, session, _ = _run("time_series", responses, config_start_date="2020-01-01")
        assert _params(session, 0)["start_date"] == "2020-01-01"

    def test_page_cap_stops_history_walk(self) -> None:
        # An arbitrarily old start date on a minute interval must not walk history unbounded.
        with (
            mock.patch.object(twelve_data, "TIME_SERIES_PAGE_SIZE", 2),
            mock.patch.object(twelve_data, "MAX_TIME_SERIES_PAGES_PER_SYMBOL", 2),
        ):
            responses = [
                _response(_time_series_body("AAPL", ["2026-07-21", "2026-07-20"])),
                _response(_time_series_body("AAPL", ["2026-07-20", "2026-07-19"])),
                # Would be page 3 — must never be requested.
                _response(_time_series_body("AAPL", ["2026-07-19", "2026-07-18"])),
            ]
            batches, session, _ = _run("time_series", responses, config_start_date="2000-01-01")
        assert session.get.call_count == 2
        assert [row["datetime"] for batch in batches for row in batch] == ["2026-07-21", "2026-07-20", "2026-07-19"]

    def test_resume_mid_symbol_seeds_end_date_and_dedupes_boundary(self) -> None:
        resume = TwelveDataResumeConfig(completed_symbols=[], current_symbol="AAPL", next_end_date="2026-07-20")
        with mock.patch.object(twelve_data, "TIME_SERIES_PAGE_SIZE", 3):
            responses = [_response(_time_series_body("AAPL", ["2026-07-20", "2026-07-19"]))]
            batches, session, _ = _run(
                "time_series",
                responses,
                manager=_make_manager(resume),
                should_use_incremental_field=True,
                db_incremental_field_last_value="2026-07-01",
            )
        assert _params(session, 0)["end_date"] == "2026-07-20"
        # The 07-20 bar was already yielded by the crashed attempt.
        assert [row["datetime"] for batch in batches for row in batch] == ["2026-07-19"]


class TestSourceResponse:
    def test_time_series_response_shape(self) -> None:
        response = twelve_data_source(
            api_key="key",
            endpoint="time_series",
            symbols=["AAPL"],
            interval="1day",
            config_start_date=None,
            resumable_source_manager=_make_manager(),
            logger=LOGGER,
        )
        assert response.primary_keys == ["symbol", "datetime"]
        # History is walked newest → oldest, so the watermark must only persist at job end.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["datetime"]

    @parameterized.expand(
        [
            ("stocks", ["symbol", "mic_code"]),
            ("exchanges", ["code"]),
            ("quotes", ["symbol"]),
            ("dividends", ["symbol", "ex_date"]),
            ("splits", ["symbol", "date"]),
            ("earnings", ["symbol", "date"]),
        ]
    )
    def test_primary_keys_and_full_refresh_shape(self, endpoint: str, primary_keys: list[str]) -> None:
        response = twelve_data_source(
            api_key="key",
            endpoint=endpoint,
            symbols=["AAPL"],
            interval="1day",
            config_start_date=None,
            resumable_source_manager=_make_manager(),
            logger=LOGGER,
        )
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_mode is None


class TestValidateCredentials:
    def test_valid_key(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response({"current_usage": 0, "plan_limit": 800})
        with mock.patch(SESSION_PATCH, return_value=session):
            assert validate_credentials("key") == (True, None)

    def test_invalid_key_surfaces_vendor_message(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(_error_body(401, "**apikey** parameter is incorrect"), status=401)
        with mock.patch(SESSION_PATCH, return_value=session):
            ok, error = validate_credentials("bad")
        assert ok is False
        assert error is not None and "401" in error

    def test_network_error_is_not_reported_as_bad_key(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = ConnectionError("boom")
        with mock.patch(SESSION_PATCH, return_value=session):
            ok, error = validate_credentials("key")
        assert ok is False
        assert error == "Could not connect to Twelve Data"
