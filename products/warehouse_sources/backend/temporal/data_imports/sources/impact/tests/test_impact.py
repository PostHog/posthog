from datetime import UTC, datetime
from typing import Any, Optional

from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.impact import impact
from products.warehouse_sources.backend.temporal.data_imports.sources.impact.impact import (
    ImpactResumeConfig,
    _discover_campaign_ids,
    _format_datetime,
    _iter_windows,
    _paginate_endpoint,
    _resume_index,
    _rows_from_response,
    _safe_int,
    _to_datetime,
    _windows_for_actions,
    get_rows,
    impact_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.impact.settings import (
    IMPACT_API_VERSION_14,
    IMPACT_API_VERSION_LEGACY,
    IMPACT_ENDPOINTS,
    IMPACT_VERSION_HEADER,
)


class FakeResumableManager:
    """Minimal stand-in for ResumableSourceManager that records saved state in memory."""

    def __init__(self, state: Optional[ImpactResumeConfig] = None):
        self.state = state
        self.saved: list[ImpactResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[ImpactResumeConfig]:
        return self.state

    def save_state(self, data: ImpactResumeConfig) -> None:
        self.saved.append(data)


class TestIterWindows:
    def test_range_shorter_than_max_is_single_window(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 10, tzinfo=UTC)
        assert list(_iter_windows(start, end, max_days=44)) == [(start, end)]

    def test_range_is_chunked_ascending_and_contiguous(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 1, tzinfo=UTC)
        windows = list(_iter_windows(start, end, max_days=44))

        assert len(windows) > 1
        assert windows[0][0] == start
        assert windows[-1][1] == end
        for i, (window_start, window_end) in enumerate(windows):
            assert window_start < window_end
            assert (window_end - window_start).days <= 44
            if i > 0:
                assert window_start == windows[i - 1][1]


class TestToDatetime:
    @parameterized.expand(
        [
            ("none", None, None),
            ("naive_string", "2024-01-01T00:00:00", datetime(2024, 1, 1, tzinfo=UTC)),
            ("z_string", "2024-01-01T00:00:00Z", datetime(2024, 1, 1, tzinfo=UTC)),
            ("garbage", "not-a-date", None),
        ]
    )
    def test_to_datetime(self, _name: str, value: Any, expected: Optional[datetime]) -> None:
        assert _to_datetime(value) == expected

    def test_naive_datetime_gets_utc(self) -> None:
        assert _to_datetime(datetime(2024, 1, 1)) == datetime(2024, 1, 1, tzinfo=UTC)


class TestFormatDatetime:
    def test_formats_as_utc_iso_with_z(self) -> None:
        assert _format_datetime(datetime(2024, 3, 5, 12, 30, 0, tzinfo=UTC)) == "2024-03-05T12:30:00Z"


class TestSafeInt:
    @parameterized.expand(
        [
            ("string", "3", 3),
            ("int", 3, 3),
            ("none", None, None),
            ("garbage", "abc", None),
        ]
    )
    def test_safe_int(self, _name: str, value: Any, expected: Optional[int]) -> None:
        assert _safe_int(value) == expected


class TestRowsFromResponse:
    def test_reads_wrapped_key(self) -> None:
        data = {"Campaigns": [{"Id": 1}, {"Id": 2}]}
        assert _rows_from_response(IMPACT_ENDPOINTS["Campaigns"], data) == [{"Id": 1}, {"Id": 2}]

    def test_missing_key_is_empty(self) -> None:
        assert _rows_from_response(IMPACT_ENDPOINTS["Campaigns"], {"@page": "1"}) == []

    def test_non_dict_rows_are_dropped(self) -> None:
        data = {"Campaigns": [{"Id": 1}, "junk", None]}
        assert _rows_from_response(IMPACT_ENDPOINTS["Campaigns"], data) == [{"Id": 1}]

    def test_non_dict_response_is_empty(self) -> None:
        assert _rows_from_response(IMPACT_ENDPOINTS["Campaigns"], ["junk"]) == []


class TestWindowsForActions:
    @freeze_time("2024-06-01")
    def test_full_refresh_backfills_max_lookback(self) -> None:
        windows = _windows_for_actions(False, None)
        assert windows[0][0] == datetime(2021, 6, 2, tzinfo=UTC)
        assert windows[-1][1] == datetime(2024, 6, 1, tzinfo=UTC)

    @freeze_time("2024-06-01")
    def test_incremental_windows_start_at_last_value(self) -> None:
        last_value = datetime(2024, 5, 1, tzinfo=UTC)
        windows = _windows_for_actions(True, last_value)
        assert windows[0][0] == last_value

    @freeze_time("2024-06-01")
    def test_cursor_older_than_max_lookback_is_clamped(self) -> None:
        # Impact rejects a StartDate more than 3 years back, so a stale cursor is clamped rather
        # than sent as-is.
        windows = _windows_for_actions(True, datetime(2015, 1, 1, tzinfo=UTC))
        assert windows[0][0] == datetime(2021, 6, 2, tzinfo=UTC)

    @freeze_time("2024-06-01")
    def test_future_cursor_yields_no_windows(self) -> None:
        assert _windows_for_actions(True, datetime(2025, 1, 1, tzinfo=UTC)) == []


class TestPaginateEndpoint:
    def test_stops_when_page_reaches_numpages(self) -> None:
        responses = [
            {"Campaigns": [{"Id": 1}], "@numpages": "2"},
            {"Campaigns": [{"Id": 2}], "@numpages": "2"},
        ]
        with patch.object(impact, "_fetch", side_effect=responses):
            pages = list(_paginate_endpoint(MagicMock(), "sid", IMPACT_ENDPOINTS["Campaigns"], {}, MagicMock()))
        assert [p for p, _rows in pages] == [1, 2]
        assert [rows for _p, rows in pages] == [[{"Id": 1}], [{"Id": 2}]]

    def test_stops_on_empty_page_even_without_numpages(self) -> None:
        responses = [{"Campaigns": [{"Id": 1}]}, {"Campaigns": []}]
        with patch.object(impact, "_fetch", side_effect=responses) as mock_fetch:
            pages = list(_paginate_endpoint(MagicMock(), "sid", IMPACT_ENDPOINTS["Campaigns"], {}, MagicMock()))
        assert len(pages) == 2
        assert mock_fetch.call_count == 2

    def test_single_page_stops_immediately(self) -> None:
        with patch.object(impact, "_fetch", return_value={"Campaigns": [{"Id": 1}], "@numpages": "1"}):
            pages = list(_paginate_endpoint(MagicMock(), "sid", IMPACT_ENDPOINTS["Campaigns"], {}, MagicMock()))
        assert len(pages) == 1

    def test_start_page_is_honored(self) -> None:
        with patch.object(impact, "_fetch", return_value={"Campaigns": [], "@numpages": "1"}) as mock_fetch:
            list(_paginate_endpoint(MagicMock(), "sid", IMPACT_ENDPOINTS["Campaigns"], {}, MagicMock(), start_page=3))
        assert mock_fetch.call_args.args[3]["Page"] == 3


class TestDiscoverCampaignIds:
    def test_dedupes_and_sorts(self) -> None:
        with patch.object(
            impact,
            "_fetch",
            return_value={"Campaigns": [{"Id": 3}, {"Id": 1}, {"Id": 2}, {"Id": 1}], "@numpages": "1"},
        ):
            assert _discover_campaign_ids(MagicMock(), "sid", MagicMock()) == [1, 2, 3]

    def test_no_campaigns_is_empty(self) -> None:
        with patch.object(impact, "_fetch", return_value={"Campaigns": [], "@numpages": "1"}):
            assert _discover_campaign_ids(MagicMock(), "sid", MagicMock()) == []


class TestResumeIndex:
    def test_no_resume_starts_at_zero(self) -> None:
        assert _resume_index([((datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC)), 1)], None) == 0

    def test_matching_bookmark_resumes_at_that_index(self) -> None:
        window = (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC))
        work_items = [(window, 1), (window, 2)]
        resume = ImpactResumeConfig(campaign_id=2, window_start=window[0].isoformat())
        assert _resume_index(work_items, resume) == 1

    def test_stale_bookmark_falls_back_to_start(self) -> None:
        window = (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC))
        work_items = [(window, 1)]
        resume = ImpactResumeConfig(campaign_id=999, window_start=window[0].isoformat())
        assert _resume_index(work_items, resume) == 0


class TestApiVersionHeader:
    def _session_headers(self, api_version: str) -> dict[str, str]:
        with patch.object(impact, "make_tracked_session") as mock_session:
            session = MagicMock()
            session.headers = {}
            mock_session.return_value = session
            impact._get_session("sid", "token", api_version)
        return session.headers

    def test_legacy_version_sends_no_version_header(self) -> None:
        headers = self._session_headers(IMPACT_API_VERSION_LEGACY)
        assert IMPACT_VERSION_HEADER not in headers

    def test_dated_version_sends_version_header(self) -> None:
        headers = self._session_headers(IMPACT_API_VERSION_14)
        assert headers[IMPACT_VERSION_HEADER] == "14"

    @parameterized.expand([(IMPACT_API_VERSION_LEGACY, False), (IMPACT_API_VERSION_14, True)])
    def test_get_rows_threads_version_to_session(self, api_version: str, expects_header: bool) -> None:
        manager = FakeResumableManager()
        with (
            patch.object(impact, "make_tracked_session") as mock_session,
            patch.object(impact, "_fetch", return_value={"Campaigns": [], "@numpages": "1"}),
        ):
            session = MagicMock()
            session.headers = {}
            mock_session.return_value = session
            list(
                get_rows(
                    "sid",
                    "token",
                    "Campaigns",
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    api_version=api_version,
                )
            )
        assert (session.headers.get(IMPACT_VERSION_HEADER) == api_version) is expects_header

    def test_validate_credentials_threads_version_to_session(self) -> None:
        with patch.object(impact, "make_tracked_session") as mock_session:
            session = MagicMock()
            session.headers = {}
            session.get.return_value = MagicMock(status_code=200)
            mock_session.return_value = session
            validate_credentials("sid", "token", IMPACT_API_VERSION_14)
        assert session.headers[IMPACT_VERSION_HEADER] == "14"


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        with patch.object(impact, "make_tracked_session") as mock_session:
            response = MagicMock()
            response.status_code = status
            mock_session.return_value.get.return_value = response
            assert validate_credentials("sid", "token") is expected

    def test_exception_is_false(self) -> None:
        with patch.object(impact, "make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("sid", "token") is False


class TestGetRowsSimple:
    def test_single_page_endpoint(self) -> None:
        manager = FakeResumableManager()
        with (
            patch.object(impact, "make_tracked_session"),
            patch.object(impact, "_fetch", return_value={"Campaigns": [{"Id": 1}], "@numpages": "1"}),
        ):
            batches = list(get_rows("sid", "token", "Campaigns", MagicMock(), manager))  # type: ignore[arg-type]
        assert batches == [[{"Id": 1}]]
        assert [s.page for s in manager.saved] == [1]

    def test_multi_page_endpoint_saves_state_per_page(self) -> None:
        manager = FakeResumableManager()
        responses = [
            {"Campaigns": [{"Id": 1}], "@numpages": "2"},
            {"Campaigns": [{"Id": 2}], "@numpages": "2"},
        ]
        with patch.object(impact, "make_tracked_session"), patch.object(impact, "_fetch", side_effect=responses):
            batches = list(get_rows("sid", "token", "Campaigns", MagicMock(), manager))  # type: ignore[arg-type]
        assert batches == [[{"Id": 1}], [{"Id": 2}]]
        assert [s.page for s in manager.saved] == [1, 2]

    def test_resume_starts_at_saved_page(self) -> None:
        manager = FakeResumableManager(state=ImpactResumeConfig(page=2))
        with (
            patch.object(impact, "make_tracked_session"),
            patch.object(impact, "_fetch", return_value={"Campaigns": [], "@numpages": "2"}) as mock_fetch,
        ):
            list(get_rows("sid", "token", "Campaigns", MagicMock(), manager))  # type: ignore[arg-type]
        assert mock_fetch.call_args.args[3]["Page"] == 2

    def test_incremental_param_sent_when_using_incremental_field(self) -> None:
        manager = FakeResumableManager()
        with (
            patch.object(impact, "make_tracked_session"),
            patch.object(impact, "_fetch", return_value={"Partners": [], "@numpages": "1"}) as mock_fetch,
        ):
            list(
                get_rows(
                    "sid",
                    "token",
                    "MediaPartners",
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value="2024-01-01T00:00:00",
                )
            )
        assert mock_fetch.call_args.args[3]["startDate"] == "2024-01-01T00:00:00Z"

    def test_no_incremental_param_when_not_incremental(self) -> None:
        manager = FakeResumableManager()
        with (
            patch.object(impact, "make_tracked_session"),
            patch.object(impact, "_fetch", return_value={"Partners": [], "@numpages": "1"}) as mock_fetch,
        ):
            list(get_rows("sid", "token", "MediaPartners", MagicMock(), manager))  # type: ignore[arg-type]
        assert "startDate" not in mock_fetch.call_args.args[3]


class TestGetRowsActions:
    @freeze_time("2024-06-01")
    def test_fanout_yields_per_campaign_and_saves_state(self) -> None:
        manager = FakeResumableManager()

        def fake_fetch(session: Any, account_sid: str, path: str, params: Any, logger: Any) -> Any:
            if path == "/Campaigns":
                return {"Campaigns": [{"Id": 10}, {"Id": 20}], "@numpages": "1"}
            return {"Actions": [{"Id": 1, "CampaignId": params["CampaignId"]}], "@numpages": "1"}

        with (
            patch.object(impact, "make_tracked_session"),
            patch.object(impact, "_fetch", side_effect=fake_fetch),
        ):
            # A last-updated value one day back keeps this to a single window per campaign.
            batches = list(
                get_rows(
                    "sid",
                    "token",
                    "Actions",
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2024, 5, 31, tzinfo=UTC),
                )
            )

        campaign_ids = {row["CampaignId"] for batch in batches for row in batch}
        assert campaign_ids == {10, 20}
        # One save per (window, campaign) work item: two campaigns, one window each.
        assert len(manager.saved) == 2 == len(batches)
        assert {s.campaign_id for s in manager.saved} == {10, 20}

    @freeze_time("2024-06-01")
    def test_no_campaigns_yields_nothing(self) -> None:
        manager = FakeResumableManager()
        with (
            patch.object(impact, "make_tracked_session"),
            patch.object(impact, "_fetch", return_value={"Campaigns": [], "@numpages": "1"}),
        ):
            batches = list(get_rows("sid", "token", "Actions", MagicMock(), manager))  # type: ignore[arg-type]
        assert batches == []

    @freeze_time("2024-06-01")
    def test_resume_skips_campaigns_before_the_bookmark(self) -> None:
        # An incremental cursor collapses the run to a single window, starting exactly at the
        # cursor value. Bookmarking campaign 20 (the middle of three) re-fetches it plus
        # everything after (merge dedupes the re-fetch); campaign 10 is skipped entirely.
        last_value = datetime(2024, 5, 30, tzinfo=UTC)
        manager = FakeResumableManager(state=ImpactResumeConfig(campaign_id=20, window_start=last_value.isoformat()))
        seen_campaigns: list[int] = []

        def fake_fetch(session: Any, account_sid: str, path: str, params: Any, logger: Any) -> Any:
            if path == "/Campaigns":
                return {"Campaigns": [{"Id": 10}, {"Id": 20}, {"Id": 30}], "@numpages": "1"}
            seen_campaigns.append(params["CampaignId"])
            return {"Actions": [], "@numpages": "1"}

        with (
            patch.object(impact, "make_tracked_session"),
            patch.object(impact, "_fetch", side_effect=fake_fetch),
        ):
            list(
                get_rows(
                    "sid",
                    "token",
                    "Actions",
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=last_value,
                )
            )
        assert seen_campaigns == [20, 30]

    @freeze_time("2024-06-01")
    def test_paired_date_params_sent(self) -> None:
        manager = FakeResumableManager()

        def fake_fetch(session: Any, account_sid: str, path: str, params: Any, logger: Any) -> Any:
            if path == "/Campaigns":
                return {"Campaigns": [{"Id": 10}], "@numpages": "1"}
            assert "ActionDateStart" in params
            assert "ActionDateEnd" in params
            return {"Actions": [], "@numpages": "1"}

        with (
            patch.object(impact, "make_tracked_session"),
            patch.object(impact, "_fetch", side_effect=fake_fetch),
        ):
            list(
                get_rows(
                    "sid",
                    "token",
                    "Actions",
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2024, 5, 30, tzinfo=UTC),
                )
            )


class TestGetRowsNested:
    def test_line_items_split_out_with_fk_and_line_number(self) -> None:
        manager = FakeResumableManager()
        invoices = {
            "Invoices": [
                {
                    "Id": "INV-1",
                    "LineItems": [
                        {"CampaignId": 10, "TotalItemAmount": "5.00"},
                        {"CampaignId": 20, "TotalItemAmount": "7.00"},
                    ],
                },
                {"Id": "INV-2", "LineItems": [{"CampaignId": 30, "TotalItemAmount": "9.00"}]},
            ],
            "@numpages": "1",
        }
        with patch.object(impact, "make_tracked_session"), patch.object(impact, "_fetch", return_value=invoices):
            batches = list(get_rows("sid", "token", "InvoiceLineItems", MagicMock(), manager))  # type: ignore[arg-type]

        rows = [row for batch in batches for row in batch]
        # Foreign key + 1-based per-invoice line number keep the composite PK unique table-wide.
        assert [(r["InvoiceId"], r["LineNumber"]) for r in rows] == [("INV-1", 1), ("INV-1", 2), ("INV-2", 1)]
        assert rows[0]["CampaignId"] == 10

    def test_detailed_line_items_use_their_own_array(self) -> None:
        manager = FakeResumableManager()
        invoices = {
            "Invoices": [
                {
                    "Id": "INV-1",
                    "LineItems": [{"CampaignId": 10}],
                    "DetailedLineItems": [{"ProgramId": 99}],
                }
            ],
            "@numpages": "1",
        }
        with patch.object(impact, "make_tracked_session"), patch.object(impact, "_fetch", return_value=invoices):
            batches = list(get_rows("sid", "token", "InvoiceDetailedLineItems", MagicMock(), manager))  # type: ignore[arg-type]

        rows = [row for batch in batches for row in batch]
        assert rows == [{"ProgramId": 99, "InvoiceId": "INV-1", "LineNumber": 1}]

    def test_invoice_without_the_array_is_skipped(self) -> None:
        manager = FakeResumableManager()
        invoices = {"Invoices": [{"Id": "INV-1"}, {"Id": "INV-2", "LineItems": []}], "@numpages": "1"}
        with patch.object(impact, "make_tracked_session"), patch.object(impact, "_fetch", return_value=invoices):
            batches = list(get_rows("sid", "token", "InvoiceLineItems", MagicMock(), manager))  # type: ignore[arg-type]
        assert batches == []


class TestGetRowsContractsFanout:
    def test_campaign_id_goes_in_path_and_is_injected_on_rows(self) -> None:
        manager = FakeResumableManager()
        seen_paths: list[str] = []

        def fake_fetch(session: Any, account_sid: str, path: str, params: Any, logger: Any) -> Any:
            if path == "/Campaigns":
                return {"Campaigns": [{"Id": 10}, {"Id": 20}], "@numpages": "1"}
            seen_paths.append(path)
            # Contracts is not scoped by a query param — the campaign lives in the path only.
            assert "CampaignId" not in params
            return {"Contracts": [{"Id": "C-1"}], "@numpages": "1"}

        with patch.object(impact, "make_tracked_session"), patch.object(impact, "_fetch", side_effect=fake_fetch):
            batches = list(get_rows("sid", "token", "Contracts", MagicMock(), manager))  # type: ignore[arg-type]

        assert seen_paths == ["/Campaigns/10/Contracts", "/Campaigns/20/Contracts"]
        injected = {row["CampaignId"] for batch in batches for row in batch}
        assert injected == {10, 20}


class TestGetRowsActionUpdates:
    @freeze_time("2024-06-01")
    def test_sends_start_and_end_date_params(self) -> None:
        manager = FakeResumableManager()

        def fake_fetch(session: Any, account_sid: str, path: str, params: Any, logger: Any) -> Any:
            if path == "/Campaigns":
                return {"Campaigns": [{"Id": 10}], "@numpages": "1"}
            assert path == "/ActionUpdates"
            assert params["CampaignId"] == 10
            assert "StartDate" in params and "EndDate" in params
            return {"ActionUpdates": [], "@numpages": "1"}

        with patch.object(impact, "make_tracked_session"), patch.object(impact, "_fetch", side_effect=fake_fetch):
            list(
                get_rows(
                    "sid",
                    "token",
                    "ActionUpdates",
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2024, 5, 30, tzinfo=UTC),
                )
            )


class TestImpactSourceResponse:
    @parameterized.expand(
        [
            ("Campaigns", ["Id"], None),
            ("MediaPartners", ["Id"], None),
            ("Invoices", ["Id"], None),
            ("Actions", ["Id"], "EventDate"),
            ("ActionUpdates", ["Id"], "ActionDate"),
            ("Contracts", ["CampaignId", "Id"], None),
            ("InvoiceLineItems", ["InvoiceId", "LineNumber"], None),
            ("InvoiceDetailedLineItems", ["InvoiceId", "LineNumber"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, expected_pks: list[str], partition_key: Optional[str]) -> None:
        response = impact_source("sid", "token", endpoint, MagicMock(), FakeResumableManager())  # type: ignore[arg-type]
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.partition_format == "month"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
