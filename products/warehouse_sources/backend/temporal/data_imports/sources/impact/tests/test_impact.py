from datetime import UTC, datetime
from typing import Any, Optional

import time_machine
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.impact import impact
from products.warehouse_sources.backend.temporal.data_imports.sources.impact.impact import (
    ImpactResumeConfig,
    _resume_index,
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


class TestWindowsForActions:
    @time_machine.travel("2024-06-01", tick=False)
    def test_full_refresh_backfills_max_lookback(self) -> None:
        windows = _windows_for_actions(False, None)
        assert windows[0][0] == datetime(2021, 6, 2, tzinfo=UTC)
        assert windows[-1][1] == datetime(2024, 6, 1, tzinfo=UTC)

    @time_machine.travel("2024-06-01", tick=False)
    def test_future_cursor_yields_no_windows(self) -> None:
        assert _windows_for_actions(True, datetime(2025, 1, 1, tzinfo=UTC)) == []


class TestResumeIndex:
    def test_stale_bookmark_falls_back_to_start(self) -> None:
        window = (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC))
        work_items = [(window, 1)]
        resume = ImpactResumeConfig(campaign_id=999, window_start=window[0].isoformat())
        assert _resume_index(work_items, resume) == 0


class TestApiVersionHeader:
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


class TestGetRowsActions:
    @time_machine.travel("2024-06-01", tick=False)
    def test_no_campaigns_yields_nothing(self) -> None:
        manager = FakeResumableManager()
        with (
            patch.object(impact, "make_tracked_session"),
            patch.object(impact, "_fetch", return_value={"Campaigns": [], "@numpages": "1"}),
        ):
            batches = list(get_rows("sid", "token", "Actions", MagicMock(), manager))  # type: ignore[arg-type]
        assert batches == []

    @time_machine.travel("2024-06-01", tick=False)
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


class TestGetRowsNested:
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
