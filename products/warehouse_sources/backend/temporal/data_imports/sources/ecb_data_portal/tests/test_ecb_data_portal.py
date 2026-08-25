from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.ecb_data_portal import (
    ECBResumeConfig,
    _coerce_start_period,
    _daterange_chunks,
    _DateWindow,
    check_connection,
    ecb_data_portal_source,
)

SESSION_FACTORY = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.ecb_data_portal"
    ".make_tracked_session"
)
TODAY_FACTORY = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.ecb_data_portal._today"
)


def _make_csv_response(csv_text: str, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = csv_text.encode()
    resp.headers["Content-Type"] = "text/csv"
    return resp


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

    def test_single_chunk_when_span_shorter_than_window(self) -> None:
        chunks = list(_daterange_chunks(date(2024, 1, 1), date(2024, 6, 1), 5))
        assert chunks == [_DateWindow(start=date(2024, 1, 1), end=date(2024, 6, 1))]

    def test_splits_into_consecutive_windows(self) -> None:
        chunks = list(_daterange_chunks(date(1999, 1, 4), date(2012, 3, 1), 5))

        assert chunks == [
            _DateWindow(start=date(1999, 1, 4), end=date(2004, 1, 3)),
            _DateWindow(start=date(2004, 1, 4), end=date(2009, 1, 3)),
            _DateWindow(start=date(2009, 1, 4), end=date(2012, 3, 1)),
        ]
        # No gaps or overlaps between consecutive windows.
        for prev_window, next_window in zip(chunks, chunks[1:]):
            assert prev_window.end is not None
            assert next_window.start is not None
            assert (next_window.start - prev_window.end).days == 1

    def test_leap_day_anchor_does_not_crash(self) -> None:
        chunks = list(_daterange_chunks(date(2000, 2, 29), date(2003, 1, 1), 1))
        assert chunks[0].start == date(2000, 2, 29)


class TestEcbDataPortalSource:
    def test_unbounded_endpoint_issues_single_request_with_no_period_params(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch(SESSION_FACTORY) as MockSession:
            mock_session = MockSession.return_value
            mock_session.get.return_value = _make_csv_response(
                _csv(("FM.B.U2.EUR.4F.KR.DFR.LEV", "2024-06-01", "3.75"))
            )

            source = ecb_data_portal_source(
                endpoint="key_interest_rates",
                resumable_source_manager=manager,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
            rows = list(cast(Iterable[dict[str, Any]], source.items()))

        assert rows == [{"KEY": "FM.B.U2.EUR.4F.KR.DFR.LEV", "TIME_PERIOD": "2024-06-01", "OBS_VALUE": "3.75"}]
        params = mock_session.get.call_args.kwargs["params"]
        assert "startPeriod" not in params
        assert "endPeriod" not in params
        manager.clear_state.assert_called_once()
        manager.save_state.assert_not_called()

    def test_sorts_rows_ascending_across_interleaved_series(self) -> None:
        # A wildcarded response groups rows by series, each internally ascending —
        # not globally ordered. The source must sort before yielding.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        csv_text = _csv(
            ("EXR.D.AUD.EUR.SP00.A", "2024-01-01", "1.6"),
            ("EXR.D.AUD.EUR.SP00.A", "2024-01-02", "1.61"),
            ("EXR.D.USD.EUR.SP00.A", "2023-12-31", "1.1"),
        )

        with patch(SESSION_FACTORY) as MockSession, patch(TODAY_FACTORY, return_value=date(2024, 1, 2)):
            MockSession.return_value.get.return_value = _make_csv_response(csv_text)
            source = ecb_data_portal_source(
                endpoint="eur_exchange_rates",
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2023-12-31",
            )
            rows = list(cast(Iterable[dict[str, Any]], source.items()))

        assert [row["TIME_PERIOD"] for row in rows] == ["2023-12-31", "2024-01-01", "2024-01-02"]

    def test_full_backfill_chunks_and_checkpoints_per_window(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch(SESSION_FACTORY) as MockSession, patch(TODAY_FACTORY, return_value=date(2011, 6, 1)):
            mock_session = MockSession.return_value
            mock_session.get.side_effect = [
                _make_csv_response(_csv(("EXR.D.USD.EUR.SP00.A", "1999-01-04", "1.18"))),
                _make_csv_response(_csv(("EXR.D.USD.EUR.SP00.A", "2004-06-01", "1.22"))),
                _make_csv_response(_csv(("EXR.D.USD.EUR.SP00.A", "2011-06-01", "1.44"))),
            ]

            source = ecb_data_portal_source(
                endpoint="eur_exchange_rates",
                resumable_source_manager=manager,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
            rows = list(cast(Iterable[dict[str, Any]], source.items()))

        assert [row["TIME_PERIOD"] for row in rows] == ["1999-01-04", "2004-06-01", "2011-06-01"]
        sent_periods = [
            (call.kwargs["params"].get("startPeriod"), call.kwargs["params"].get("endPeriod"))
            for call in mock_session.get.call_args_list
        ]
        assert sent_periods == [
            ("1999-01-04", "2004-01-03"),
            ("2004-01-04", "2009-01-03"),
            ("2009-01-04", "2011-06-01"),
        ]
        # A checkpoint after each of the first two (incomplete) windows, none after the last.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            ECBResumeConfig(next_start_period="2004-01-04"),
            ECBResumeConfig(next_start_period="2009-01-04"),
        ]
        manager.clear_state.assert_called_once()

    def test_resumes_from_saved_checkpoint(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ECBResumeConfig(next_start_period="2009-01-04")

        with patch(SESSION_FACTORY) as MockSession, patch(TODAY_FACTORY, return_value=date(2011, 6, 1)):
            mock_session = MockSession.return_value
            mock_session.get.return_value = _make_csv_response(_csv(("EXR.D.USD.EUR.SP00.A", "2011-06-01", "1.44")))

            source = ecb_data_portal_source(
                endpoint="eur_exchange_rates",
                resumable_source_manager=manager,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
            list(cast(Iterable[dict[str, Any]], source.items()))

        assert mock_session.get.call_count == 1
        params = mock_session.get.call_args.kwargs["params"]
        assert params["startPeriod"] == "2009-01-04"

    def test_no_observations_in_window_yields_nothing_and_does_not_raise(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch(SESSION_FACTORY) as MockSession:
            MockSession.return_value.get.return_value = _make_csv_response("", status_code=404)

            source = ecb_data_portal_source(
                endpoint="hicp_inflation",
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2099-01-01",
            )
            rows = list(cast(Iterable[dict[str, Any]], source.items()))

        assert rows == []

    def test_waf_block_raises_non_retryable_shaped_error(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        block_page = "<html>...Your access has been blocked due to security concerns...</html>"

        with patch(SESSION_FACTORY) as MockSession:
            MockSession.return_value.get.return_value = _make_csv_response(block_page, status_code=400)

            source = ecb_data_portal_source(
                endpoint="hicp_inflation",
                resumable_source_manager=manager,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
            with pytest.raises(ValueError, match="Your access has been blocked due to security concerns"):
                list(cast(Iterable[dict[str, Any]], source.items()))


class TestCheckConnection:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (503, False),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with patch(SESSION_FACTORY) as MockSession:
            response = MagicMock()
            response.status_code = status_code
            MockSession.return_value.get.return_value = response

            valid, error = check_connection()

        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_network_error_returns_message(self) -> None:
        with patch(SESSION_FACTORY) as MockSession:
            MockSession.return_value.get.side_effect = Exception("boom")
            valid, error = check_connection()

        assert valid is False
        assert error == "boom"
