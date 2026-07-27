import io
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.adyen import adyen as adyen_module
from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.adyen import (
    MAX_CONSECUTIVE_MISSING_BATCHES,
    MAX_WINDOW_DAYS,
    PAGE_SIZE,
    AdyenConfigurationError,
    AdyenResumeConfig,
    _iter_cursor_pages,
    _require_identifier,
    _to_batch_number,
    _to_datetime,
    adyen_source,
    base_url,
    extract_items,
    get_rows,
    iter_windows,
    next_cursor,
    normalize_header,
    parse_report_rows,
    resolve_environment,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.settings import ADYEN_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class _FakeRaw:
    """Stand-in for `response.raw`: a readable byte stream the report path streams CSV off."""

    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)
        self.decode_content = False

    def read(self, *args: Any, **kwargs: Any) -> bytes:
        return self._buffer.read(*args, **kwargs)


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Optional[dict[str, Any]] = None, text: str = "") -> None:
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text
        self.raw = _FakeRaw(text.encode())
        self.closed = False

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> dict[str, Any]:
        return self._json_data

    def raise_for_status(self) -> None:
        if not self.ok:
            raise Exception(f"{self.status_code} Client Error for url")

    def close(self) -> None:
        self.closed = True


class _FakeSession:
    """Replays a queued list of responses and records the URLs that were requested."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.requested_urls: list[str] = []
        self.requested_headers: list[Optional[dict[str, str]]] = []

    def get(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[int] = None,
        stream: bool = False,
    ) -> _FakeResponse:
        self.requested_urls.append(url)
        self.requested_headers.append(headers)
        if not self._responses:
            raise AssertionError(f"unexpected request to {url}")
        return self._responses.pop(0)


class _FakeManager(ResumableSourceManager[AdyenResumeConfig]):
    """In-memory stand-in for the Redis-backed manager (no `super().__init__`)."""

    def __init__(self, resume_state: Optional[AdyenResumeConfig] = None) -> None:
        self._resume_state = resume_state
        self.saved_states: list[AdyenResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_state is not None

    def load_state(self) -> Optional[AdyenResumeConfig]:
        return self._resume_state

    def save_state(self, data: AdyenResumeConfig) -> None:
        self.saved_states.append(data)


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def _drain(
    session: _FakeSession,
    endpoint: str,
    manager: _FakeManager,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    with mock.patch.object(adyen_module, "_get_session", return_value=session):
        rows: list[dict[str, Any]] = []
        for batch in get_rows(
            environment="test",
            api_key="key",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=manager,
            **kwargs,
        ):
            rows.extend(batch)
        return rows


class TestHosts:
    @parameterized.expand(
        [
            ("test_transfers", "test", "transfers", "https://balanceplatform-api-test.adyen.com/btl/v4"),
            ("live_transfers", "live", "transfers", "https://balanceplatform-api-live.adyen.com/btl/v4"),
            ("test_configuration", "test", "configuration", "https://balanceplatform-api-test.adyen.com/bcl/v2"),
            ("live_management", "live", "management", "https://management-live.adyen.com/v3"),
            ("test_reports", "test", "reports", "https://ca-test.adyen.com"),
            # An unrecognised environment can never retarget the API key at another host.
            ("unknown_falls_back_to_live", "evil.example.com", "management", "https://management-live.adyen.com/v3"),
            ("none_falls_back_to_live", None, "reports", "https://ca-live.adyen.com"),
        ]
    )
    def test_base_url(self, _name: str, environment: Optional[str], api: Any, expected: str) -> None:
        assert base_url(environment, api) == expected

    @parameterized.expand([("test", "test", "test"), ("live", "live", "live"), ("junk", "junk", "live")])
    def test_resolve_environment(self, _name: str, value: str, expected: str) -> None:
        assert resolve_environment(value) == expected


class TestRequireIdentifier:
    def test_accepts_a_plain_identifier(self) -> None:
        assert _require_identifier("  YOUR_BALANCE_PLATFORM  ", "Balance platform ID") == "YOUR_BALANCE_PLATFORM"

    @parameterized.expand(
        [
            ("empty", ""),
            ("whitespace", "   "),
            ("none", None),
            ("path_traversal", "../../secrets"),
            ("slash", "acct/other"),
            ("query_injection", "acct?limit=1"),
        ]
    )
    def test_rejects_unusable_values(self, _name: str, value: Optional[str]) -> None:
        with pytest.raises(AdyenConfigurationError):
            _require_identifier(value, "Merchant account")


class TestCoercion:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC), datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)),
            ("naive_datetime", datetime(2026, 3, 4, 5, 6, 7), datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)),
            ("date", date(2026, 3, 4), datetime(2026, 3, 4, tzinfo=UTC)),
            ("iso_string", "2026-03-04T05:06:07Z", datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)),
            ("date_string", "2026-03-04", datetime(2026, 3, 4, tzinfo=UTC)),
            ("garbage", "not-a-date", None),
            ("none", None, None),
        ]
    )
    def test_to_datetime(self, _name: str, value: Any, expected: Optional[datetime]) -> None:
        assert _to_datetime(value) == expected

    @parameterized.expand(
        [("int", 12, 12), ("str", "12", 12), ("float_str", "12.0", 12), ("garbage", "abc", None), ("none", None, None)]
    )
    def test_to_batch_number(self, _name: str, value: Any, expected: Optional[int]) -> None:
        assert _to_batch_number(value) == expected


class TestIterWindows:
    def test_short_range_is_a_single_window(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=3)
        assert list(iter_windows(start, end)) == [(start, end)]

    def test_long_range_is_split_into_contiguous_ascending_windows(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=MAX_WINDOW_DAYS * 2 + 10)

        windows = list(iter_windows(start, end))

        assert len(windows) == 3
        assert windows[0][0] == start
        assert windows[-1][1] == end
        for (_, previous_end), (next_start, _) in zip(windows, windows[1:]):
            assert previous_end == next_start
        for window_start, window_end in windows:
            assert window_end - window_start <= timedelta(days=MAX_WINDOW_DAYS)

    @parameterized.expand([("equal", 0), ("inverted", -5)])
    def test_no_windows_when_end_not_after_start(self, _name: str, offset_days: int) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        assert list(iter_windows(start, start + timedelta(days=offset_days))) == []


class TestResponseParsing:
    @parameterized.expand(
        [
            (
                "cursor_present",
                {"_links": {"next": {"href": "https://x/btl/v4/transfers?cursor=abc&limit=100"}}},
                "abc",
            ),
            ("no_links", {"data": []}, None),
            ("no_next", {"_links": {"prev": {"href": "https://x?cursor=old"}}}, None),
            ("next_without_cursor", {"_links": {"next": {"href": "https://x/btl/v4/transfers?limit=100"}}}, None),
            ("next_not_an_object", {"_links": {"next": "https://x?cursor=abc"}}, None),
            ("not_a_dict", ["nope"], None),
        ]
    )
    def test_next_cursor(self, _name: str, payload: Any, expected: Optional[str]) -> None:
        assert next_cursor(payload) == expected

    @parameterized.expand(
        [
            ("keyed", {"data": [{"id": "1"}]}, "data", [{"id": "1"}]),
            ("missing_key", {"other": [{"id": "1"}]}, "data", []),
            ("bare_list", [{"id": "1"}], None, [{"id": "1"}]),
            ("non_dict_items_dropped", {"data": [{"id": "1"}, "junk", None]}, "data", [{"id": "1"}]),
            ("non_list_value", {"data": {"id": "1"}}, "data", []),
        ]
    )
    def test_extract_items(
        self, _name: str, payload: Any, data_key: Optional[str], expected: list[dict[str, Any]]
    ) -> None:
        assert extract_items(payload, data_key) == expected


class TestReportParsing:
    @parameterized.expand(
        [
            ("simple", "Psp Reference", "psp_reference"),
            ("parenthesised", "Gross Debit (GC)", "gross_debit_gc"),
            ("already_snake", "batch_number", "batch_number"),
            ("mixed_punctuation", "Modification Merchant Reference", "modification_merchant_reference"),
        ]
    )
    def test_normalize_header(self, _name: str, header: str, expected: str) -> None:
        assert normalize_header(header) == expected

    def test_rows_are_normalized_and_stamped_with_the_requested_batch(self) -> None:
        text = "Psp Reference,Type,Gross Debit (GC),Batch Number\nABC123,Settled,10.00,7\n"

        rows = list(parse_report_rows(io.StringIO(text), 7, mock.MagicMock()))

        assert rows == [
            {
                "psp_reference": "ABC123",
                "type": "Settled",
                "gross_debit_gc": "10.00",
                # The requested batch is the authoritative integer watermark, so it overrides
                # the report's own string column.
                "batch_number": 7,
            }
        ]

    def test_blank_and_malformed_rows_are_skipped(self) -> None:
        logger = mock.MagicMock()
        text = "Psp Reference,Type\nABC,Settled\n\nSHORT\nDEF,Refunded\n"

        rows = list(parse_report_rows(io.StringIO(text), 1, logger))

        assert [row["psp_reference"] for row in rows] == ["ABC", "DEF"]
        assert logger.warning.call_count == 1

    def test_empty_report_yields_nothing(self) -> None:
        assert list(parse_report_rows(io.StringIO(""), 1, mock.MagicMock())) == []


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            # A report-only credential legitimately lacks the Management API role.
            ("forbidden_is_still_a_real_key", 403, True),
            ("unauthorized", 401, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        session = _FakeSession([_FakeResponse(status_code=status_code)])
        with mock.patch.object(adyen_module, "_get_session", return_value=session):
            is_valid, message = validate_credentials("test", "key")

        assert is_valid is expected_valid
        assert (message is None) is expected_valid
        assert session.requested_urls == ["https://management-test.adyen.com/v3/me"]

    @parameterized.expand([("reachable", 200, True), ("still_rejected", 401, False)])
    def test_balance_platform_key_unknown_to_the_management_api_falls_back(
        self, _name: str, fallback_status: int, expected_valid: bool
    ) -> None:
        # A key issued in a Balance Platform Customer Area can 401 against Management API.
        session = _FakeSession([_FakeResponse(status_code=401), _FakeResponse(status_code=fallback_status)])
        with mock.patch.object(adyen_module, "_get_session", return_value=session):
            is_valid, _ = validate_credentials("test", "key", balance_platform="BP123")

        assert is_valid is expected_valid
        assert session.requested_urls[1] == "https://balanceplatform-api-test.adyen.com/bcl/v2/balancePlatforms/BP123"

    def test_no_fallback_without_a_balance_platform(self) -> None:
        session = _FakeSession([_FakeResponse(status_code=401)])
        with mock.patch.object(adyen_module, "_get_session", return_value=session):
            is_valid, _ = validate_credentials("test", "key")

        assert is_valid is False
        assert len(session.requested_urls) == 1

    def test_malformed_identifier_fails_before_any_request(self) -> None:
        session = _FakeSession([])
        with mock.patch.object(adyen_module, "_get_session", return_value=session):
            is_valid, message = validate_credentials("test", "key", merchant_account="../etc")

        assert is_valid is False
        assert message is not None
        assert session.requested_urls == []

    def test_transport_failure_is_reported_not_raised(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = adyen_module.requests.exceptions.ConnectionError("boom")
        with mock.patch.object(adyen_module, "_get_session", return_value=session):
            is_valid, message = validate_credentials("live", "key")

        assert is_valid is False
        assert message == "boom"


class TestCursorPagination:
    def _pages(self, session: _FakeSession, manager: _FakeManager, resume: Optional[AdyenResumeConfig] = None) -> list:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        return list(
            _iter_cursor_pages(
                session=cast(Any, session),
                config=ADYEN_ENDPOINTS["Transfers"],
                host="https://balanceplatform-api-test.adyen.com/btl/v4",
                balance_platform="BP123",
                start=start,
                end=start + timedelta(days=1),
                logger=mock.MagicMock(),
                manager=manager,
                resume=resume,
            )
        )

    def test_walks_pages_until_the_cursor_runs_out(self) -> None:
        session = _FakeSession(
            [
                _FakeResponse(
                    json_data={"data": [{"id": "t1"}], "_links": {"next": {"href": "https://x?cursor=c2"}}},
                ),
                _FakeResponse(json_data={"data": [{"id": "t2"}]}),
            ]
        )
        manager = _FakeManager()

        pages = self._pages(session, manager)

        assert [item["id"] for page in pages for item in page] == ["t1", "t2"]
        assert _query(session.requested_urls[1])["cursor"] == ["c2"]

    def test_first_request_carries_the_required_window_and_sort(self) -> None:
        session = _FakeSession([_FakeResponse(json_data={"data": []})])

        self._pages(session, _FakeManager())

        params = _query(session.requested_urls[0])
        assert params["balancePlatform"] == ["BP123"]
        assert params["createdSince"] == ["2026-01-01T00:00:00Z"]
        assert params["createdUntil"] == ["2026-01-02T00:00:00Z"]
        assert params["sortOrder"] == ["asc"]
        assert params["limit"] == [str(PAGE_SIZE)]
        assert "cursor" not in params

    def test_state_is_saved_after_each_yielded_page(self) -> None:
        session = _FakeSession(
            [
                _FakeResponse(json_data={"data": [{"id": "t1"}], "_links": {"next": {"href": "https://x?cursor=c2"}}}),
                _FakeResponse(json_data={"data": [{"id": "t2"}]}),
            ]
        )
        manager = _FakeManager()

        self._pages(session, manager)

        assert [state.cursor for state in manager.saved_states] == ["c2"]
        assert manager.saved_states[0].window_start == "2026-01-01T00:00:00Z"

    def test_resume_starts_from_the_saved_cursor(self) -> None:
        session = _FakeSession([_FakeResponse(json_data={"data": [{"id": "t9"}]})])
        resume = AdyenResumeConfig(window_start="2026-01-01T00:00:00Z", cursor="saved-cursor")

        pages = self._pages(session, _FakeManager(resume), resume=resume)

        assert [item["id"] for page in pages for item in page] == ["t9"]
        assert _query(session.requested_urls[0])["cursor"] == ["saved-cursor"]

    def test_windows_before_the_saved_one_are_skipped(self) -> None:
        session = _FakeSession([_FakeResponse(json_data={"data": [{"id": "later"}]})])
        start = datetime(2026, 1, 1, tzinfo=UTC)
        resume_window = start + timedelta(days=MAX_WINDOW_DAYS)
        manager = _FakeManager()

        pages = list(
            _iter_cursor_pages(
                session=cast(Any, session),
                config=ADYEN_ENDPOINTS["Transactions"],
                host="https://balanceplatform-api-test.adyen.com/btl/v4",
                balance_platform="BP123",
                start=start,
                end=start + timedelta(days=MAX_WINDOW_DAYS + 5),
                logger=mock.MagicMock(),
                manager=manager,
                resume=AdyenResumeConfig(window_start=resume_window.strftime("%Y-%m-%dT%H:%M:%SZ")),
            )
        )

        # Only the second window is requested; the first was already completed.
        assert len(session.requested_urls) == 1
        assert _query(session.requested_urls[0])["createdSince"] == [resume_window.strftime("%Y-%m-%dT%H:%M:%SZ")]
        assert [item["id"] for page in pages for item in page] == ["later"]

    def test_missing_balance_platform_is_a_configuration_error(self) -> None:
        with pytest.raises(AdyenConfigurationError):
            _drain(_FakeSession([]), "Transfers", _FakeManager())


class TestOffsetPagination:
    def test_stops_on_a_short_page_and_checkpoints_the_offset(self) -> None:
        session = _FakeSession(
            [
                _FakeResponse(json_data={"accountHolders": [{"id": f"AH{i}"} for i in range(PAGE_SIZE)]}),
                _FakeResponse(json_data={"accountHolders": [{"id": "AH-last"}]}),
            ]
        )
        manager = _FakeManager()

        rows = _drain(session, "AccountHolders", manager, balance_platform="BP123")

        assert len(rows) == PAGE_SIZE + 1
        assert _query(session.requested_urls[0])["offset"] == ["0"]
        assert _query(session.requested_urls[1])["offset"] == [str(PAGE_SIZE)]
        assert [state.offset for state in manager.saved_states] == [PAGE_SIZE]

    def test_resumes_from_the_saved_offset(self) -> None:
        session = _FakeSession([_FakeResponse(json_data={"accountHolders": [{"id": "AH9"}]})])

        rows = _drain(
            session,
            "AccountHolders",
            _FakeManager(AdyenResumeConfig(offset=200)),
            balance_platform="BP123",
        )

        assert [row["id"] for row in rows] == ["AH9"]
        assert _query(session.requested_urls[0])["offset"] == ["200"]

    def test_empty_first_page_yields_nothing(self) -> None:
        session = _FakeSession([_FakeResponse(json_data={"accountHolders": []})])

        assert _drain(session, "AccountHolders", _FakeManager(), balance_platform="BP123") == []


class TestPageNumberPagination:
    def test_stops_once_pages_total_is_reached(self) -> None:
        session = _FakeSession(
            [
                _FakeResponse(
                    json_data={"data": [{"id": f"M{i}"} for i in range(PAGE_SIZE)], "pagesTotal": 2},
                ),
                _FakeResponse(
                    json_data={"data": [{"id": f"N{i}"} for i in range(PAGE_SIZE)], "pagesTotal": 2},
                ),
            ]
        )
        manager = _FakeManager()

        rows = _drain(session, "MerchantAccounts", manager)

        assert len(rows) == PAGE_SIZE * 2
        assert _query(session.requested_urls[0])["pageNumber"] == ["1"]
        assert _query(session.requested_urls[1])["pageNumber"] == ["2"]
        assert [state.page_number for state in manager.saved_states] == [2]

    def test_resumes_from_the_saved_page(self) -> None:
        session = _FakeSession([_FakeResponse(json_data={"data": [{"id": "C1"}], "pagesTotal": 4})])

        rows = _drain(session, "Companies", _FakeManager(AdyenResumeConfig(page_number=3)))

        assert [row["id"] for row in rows] == ["C1"]
        assert _query(session.requested_urls[0])["pageNumber"] == ["3"]


class TestFanout:
    def test_children_are_fetched_per_parent_and_checkpointed(self) -> None:
        session = _FakeSession(
            [
                _FakeResponse(json_data={"accountHolders": [{"id": "AH1"}, {"id": "AH2"}]}),
                _FakeResponse(json_data={"balanceAccounts": [{"id": "BA1", "accountHolderId": "AH1"}]}),
                _FakeResponse(json_data={"balanceAccounts": [{"id": "BA2", "accountHolderId": "AH2"}]}),
            ]
        )
        manager = _FakeManager()

        rows = _drain(session, "BalanceAccounts", manager, balance_platform="BP123")

        assert [row["id"] for row in rows] == ["BA1", "BA2"]
        assert session.requested_urls[1].startswith(
            "https://balanceplatform-api-test.adyen.com/bcl/v2/accountHolders/AH1/balanceAccounts"
        )
        assert [state.parent_index for state in manager.saved_states] == [1, 2]

    def test_resume_skips_parents_already_walked(self) -> None:
        session = _FakeSession(
            [
                _FakeResponse(json_data={"accountHolders": [{"id": "AH1"}, {"id": "AH2"}]}),
                _FakeResponse(json_data={"balanceAccounts": [{"id": "BA2"}]}),
            ]
        )

        rows = _drain(
            session,
            "BalanceAccounts",
            _FakeManager(AdyenResumeConfig(parent_index=1)),
            balance_platform="BP123",
        )

        assert [row["id"] for row in rows] == ["BA2"]
        assert "AH2" in session.requested_urls[1]


class TestReportBatches:
    def _report(self, rows: str) -> _FakeResponse:
        return _FakeResponse(text=f"Psp Reference,Type,Modification Reference\n{rows}")

    def test_walks_ascending_batches_until_the_gap_tolerance_is_exhausted(self) -> None:
        session = _FakeSession(
            [
                self._report("A,Settled,\n"),
                _FakeResponse(status_code=404),
                self._report("B,Fee,\n"),
                *[_FakeResponse(status_code=404) for _ in range(MAX_CONSECUTIVE_MISSING_BATCHES + 1)],
            ]
        )
        manager = _FakeManager()

        rows = _drain(session, "SettlementDetailReports", manager, merchant_account="ACME")

        assert [(row["psp_reference"], row["batch_number"]) for row in rows] == [("A", 1), ("B", 3)]
        assert [state.batch_number for state in manager.saved_states] == [1, 3]
        assert session.requested_urls[0].endswith(
            "/reports/download/MerchantAccount/ACME/settlement_detail_report_batch_1.csv"
        )

    def test_requests_gzip_and_csv(self) -> None:
        session = _FakeSession([self._report("A,Settled,\n"), *[_FakeResponse(status_code=404) for _ in range(4)]])

        _drain(session, "SettlementDetailReports", _FakeManager(), merchant_account="ACME")

        headers = session.requested_headers[0]
        assert headers is not None
        assert headers["Accept-Encoding"] == "gzip"
        assert headers["Accept"] == "text/csv"

    def test_incremental_watermark_starts_at_the_next_batch(self) -> None:
        session = _FakeSession([self._report("C,Settled,\n"), *[_FakeResponse(status_code=404) for _ in range(4)]])

        rows = _drain(
            session,
            "SettlementDetailReports",
            _FakeManager(),
            merchant_account="ACME",
            should_use_incremental_field=True,
            db_incremental_field_last_value=41,
        )

        assert rows[0]["batch_number"] == 42
        assert session.requested_urls[0].endswith("settlement_detail_report_batch_42.csv")

    def test_resume_state_wins_over_the_watermark(self) -> None:
        session = _FakeSession([self._report("D,Settled,\n"), *[_FakeResponse(status_code=404) for _ in range(4)]])

        _drain(
            session,
            "SettlementDetailReports",
            _FakeManager(AdyenResumeConfig(batch_number=100)),
            merchant_account="ACME",
            should_use_incremental_field=True,
            db_incremental_field_last_value=41,
        )

        assert session.requested_urls[0].endswith("settlement_detail_report_batch_101.csv")

    def test_configured_start_batch_is_used_on_a_first_full_sync(self) -> None:
        session = _FakeSession([self._report("E,Settled,\n"), *[_FakeResponse(status_code=404) for _ in range(4)]])

        _drain(
            session,
            "SettlementDetailReports",
            _FakeManager(),
            merchant_account="ACME",
            settlement_report_start_batch=500,
        )

        assert session.requested_urls[0].endswith("settlement_detail_report_batch_500.csv")

    @parameterized.expand([("forbidden", 403), ("server_error", 500)])
    def test_non_404_failures_are_raised(self, _name: str, status_code: int) -> None:
        session = _FakeSession([_FakeResponse(status_code=status_code)])

        with pytest.raises(Exception, match="Client Error|Error for url"):
            _drain(session, "SettlementDetailReports", _FakeManager(), merchant_account="ACME")

    def test_missing_merchant_account_is_a_configuration_error(self) -> None:
        with pytest.raises(AdyenConfigurationError):
            _drain(_FakeSession([]), "SettlementDetailReports", _FakeManager())


class TestAdyenSourceResponse:
    @parameterized.expand([(name,) for name in ADYEN_ENDPOINTS])
    def test_response_matches_the_endpoint_catalog(self, endpoint: str) -> None:
        config = ADYEN_ENDPOINTS[endpoint]

        response = adyen_source(
            environment="test",
            api_key="key",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=_FakeManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == list(config.primary_key)
        # Every endpoint is walked oldest-first, so the watermark only moves forward.
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_items_are_lazy(self) -> None:
        # Building the response must not touch the network — the pipeline calls `items()`.
        response = adyen_source(
            environment="test",
            api_key="key",
            endpoint="Transfers",
            logger=mock.MagicMock(),
            resumable_source_manager=_FakeManager(),
        )

        assert callable(response.items)
        with mock.patch.object(adyen_module, "_get_session", return_value=_FakeSession([])):
            with pytest.raises(AdyenConfigurationError):
                list(cast("Iterable[Any]", response.items()))
