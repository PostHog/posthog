from datetime import date, datetime
from typing import Any

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.ecb_data_portal import (
    ECBResumeConfig,
    _coerce_start_period,
    _daterange_chunks,
    _DateWindow,
    check_connection,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.source import EcbDataPortalSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ecbdataportal import (
    EcbDataPortalSourceConfig,
)

TODAY_FACTORY = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.ecb_data_portal._today"
)


def _csv_response(csv_text: str, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, body=csv_text.encode(), headers={"Content-Type": "text/csv"})


def _csv(*rows: tuple[str, str, str]) -> str:
    lines = ["KEY,TIME_PERIOD,OBS_VALUE"]
    lines.extend(f"{key},{period},{value}" for key, period, value in rows)
    return "\n".join(lines)


class TestCoerceStartPeriod:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, None),
            (date(2024, 1, 1), date(2024, 1, 1)),
            (datetime(2024, 1, 1, 12, 30), date(2024, 1, 1)),
            ("2024-01-01", date(2024, 1, 1)),
            ("2024-01", date(2024, 1, 1)),
            ("not-a-date", None),
        ],
    )
    def test_coerces_supported_shapes(self, value: Any, expected: date | None) -> None:
        assert _coerce_start_period(value) == expected


class TestDaterangeChunks:
    def test_unbounded_when_chunk_years_is_none(self) -> None:
        chunks = list(_daterange_chunks(date(1999, 1, 4), date(2026, 8, 17), None))
        assert chunks == [_DateWindow(start=date(1999, 1, 4), end=None)]

    def test_unbounded_when_no_start_date(self) -> None:
        chunks = list(_daterange_chunks(None, date(2026, 8, 17), 5))
        assert chunks == [_DateWindow(start=None, end=None)]

    def test_leap_day_anchor_does_not_crash(self) -> None:
        chunks = list(_daterange_chunks(date(2000, 2, 29), date(2003, 1, 1), 1))
        assert chunks[0].start == date(2000, 2, 29)


class TestEcbDataPortalSource:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(EcbDataPortalSource(), EcbDataPortalSourceConfig())

    def test_unbounded_endpoint_issues_single_request_with_no_period_params(self) -> None:
        result = self._driver().run(
            "key_interest_rates", [_csv_response(_csv(("FM.B.U2.EUR.4F.KR.DFR.LEV", "2024-06-01", "3.75")))]
        )

        assert result.raised is None
        assert result.rows == [{"KEY": "FM.B.U2.EUR.4F.KR.DFR.LEV", "TIME_PERIOD": "2024-06-01", "OBS_VALUE": "3.75"}]
        assert len(result.requests) == 1
        assert result.params("startPeriod") == [None]
        assert result.params("endPeriod") == [None]
        assert result.final_state is None
        assert result.saved_states == []

    def test_sorts_rows_ascending_across_interleaved_series(self) -> None:
        # A wildcarded response groups rows by series, each internally ascending —
        # not globally ordered. The source must sort before yielding.
        csv_text = _csv(
            ("EXR.D.AUD.EUR.SP00.A", "2024-01-01", "1.6"),
            ("EXR.D.AUD.EUR.SP00.A", "2024-01-02", "1.61"),
            ("EXR.D.USD.EUR.SP00.A", "2023-12-31", "1.1"),
        )

        with patch(TODAY_FACTORY, return_value=date(2024, 1, 2)):
            result = self._driver().run(
                "eur_exchange_rates",
                [_csv_response(csv_text)],
                incremental_field="TIME_PERIOD",
                db_incremental_field_last_value="2023-12-31",
            )

        assert result.raised is None
        assert [row["TIME_PERIOD"] for row in result.rows] == ["2023-12-31", "2024-01-01", "2024-01-02"]

    def test_full_backfill_chunks_and_checkpoints_per_window(self) -> None:
        with patch(TODAY_FACTORY, return_value=date(2011, 6, 1)):
            result = self._driver().run(
                "eur_exchange_rates",
                [
                    _csv_response(_csv(("EXR.D.USD.EUR.SP00.A", "1999-01-04", "1.18"))),
                    _csv_response(_csv(("EXR.D.USD.EUR.SP00.A", "2004-06-01", "1.22"))),
                    _csv_response(_csv(("EXR.D.USD.EUR.SP00.A", "2011-06-01", "1.44"))),
                ],
            )

        assert result.raised is None
        assert [row["TIME_PERIOD"] for row in result.rows] == ["1999-01-04", "2004-06-01", "2011-06-01"]
        sent_periods = list(zip(result.params("startPeriod"), result.params("endPeriod")))
        assert sent_periods == [
            ("1999-01-04", "2004-01-03"),
            ("2004-01-04", "2009-01-03"),
            ("2009-01-04", "2011-06-01"),
        ]
        # A checkpoint after each of the first two (incomplete) windows, none after the last.
        assert result.saved_states == [
            ECBResumeConfig(next_start_period="2004-01-04"),
            ECBResumeConfig(next_start_period="2009-01-04"),
        ]
        assert result.committed_states == result.saved_states
        assert result.final_state is None

    def test_resumes_from_saved_checkpoint(self) -> None:
        with patch(TODAY_FACTORY, return_value=date(2011, 6, 1)):
            result = self._driver().run(
                "eur_exchange_rates",
                [_csv_response(_csv(("EXR.D.USD.EUR.SP00.A", "2011-06-01", "1.44")))],
                resume_state=ECBResumeConfig(next_start_period="2009-01-04"),
            )

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.params("startPeriod") == ["2009-01-04"]

    def test_no_observations_in_window_yields_nothing_and_does_not_raise(self) -> None:
        result = self._driver().run(
            "hicp_inflation",
            [_csv_response("", status_code=404)],
            incremental_field="TIME_PERIOD",
            db_incremental_field_last_value="2099-01-01",
        )

        assert result.raised is None
        assert result.rows == []

    def test_waf_block_raises_non_retryable_shaped_error(self) -> None:
        block_page = "<html>...Your access has been blocked due to security concerns...</html>"

        result = self._driver().run("hicp_inflation", [_csv_response(block_page, status_code=400)])

        assert isinstance(result.raised, ValueError)
        assert "Your access has been blocked due to security concerns" in str(result.raised)


class TestCheckConnection:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (503, False),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, error = check_connection()

        assert {request.path for request in network.requests_log} == {"/service/data/EXR/D.USD.EUR.SP00.A"}
        assert all(request.param("lastNObservations") == "1" for request in network.requests_log)
        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_network_error_returns_message(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            valid, error = check_connection()

        assert valid is False
        assert error is not None
        assert "boom" in error
