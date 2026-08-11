from datetime import UTC, datetime
from typing import Any, Optional

from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.impact_partner import impact_partner
from products.warehouse_sources.backend.temporal.data_imports.sources.impact_partner.impact_partner import (
    ImpactPartnerResumeConfig,
    _get_session,
    _resume_window_index,
    _windows_for_actions,
    get_rows,
    impact_partner_source,
    validate_credentials,
)

API_VERSION = "16"


class FakeResumableManager:
    """Minimal stand-in for ResumableSourceManager that records saved state in memory."""

    def __init__(self, state: Optional[ImpactPartnerResumeConfig] = None):
        self.state = state
        self.saved: list[ImpactPartnerResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[ImpactPartnerResumeConfig]:
        return self.state

    def save_state(self, data: ImpactPartnerResumeConfig) -> None:
        self.saved.append(data)


class TestGetSession:
    def test_session_pins_api_version_and_accepts_json(self) -> None:
        with patch.object(impact_partner, "make_tracked_session") as mock_session:
            mock_session.return_value.headers = {}
            session = _get_session("sid", "token", API_VERSION)
        assert session.headers["Accept"] == "application/json"
        assert session.headers["IR-Version"] == API_VERSION


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        with patch.object(impact_partner, "make_tracked_session") as mock_session:
            mock_session.return_value.headers = {}
            response = MagicMock()
            response.status_code = status
            mock_session.return_value.get.return_value = response
            assert validate_credentials("sid", "token", API_VERSION) is expected

    def test_calls_the_partner_base_path(self) -> None:
        with patch.object(impact_partner, "make_tracked_session") as mock_session:
            mock_session.return_value.headers = {}
            response = MagicMock()
            response.status_code = 200
            mock_session.return_value.get.return_value = response
            validate_credentials("sid", "token", API_VERSION)
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == "https://api.impact.com/Mediapartners/sid/Campaigns"

    def test_exception_is_false(self) -> None:
        with patch.object(impact_partner, "make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("sid", "token", API_VERSION) is False


class TestWindowsForActions:
    @freeze_time("2026-06-01")
    def test_full_refresh_backfills_max_lookback(self) -> None:
        windows = _windows_for_actions(False, None)
        assert windows[0][0] == datetime(2023, 6, 2, tzinfo=UTC)
        assert windows[-1][1] == datetime(2026, 6, 1, tzinfo=UTC)

    @freeze_time("2026-06-01")
    def test_cursor_older_than_max_lookback_is_clamped(self) -> None:
        # Impact rejects a start date more than 3 years back, so a stale cursor is clamped
        # rather than sent as-is.
        windows = _windows_for_actions(True, datetime(2015, 1, 1, tzinfo=UTC))
        assert windows[0][0] == datetime(2023, 6, 2, tzinfo=UTC)

    @freeze_time("2026-06-01")
    def test_future_cursor_yields_no_windows(self) -> None:
        assert _windows_for_actions(True, datetime(2027, 1, 1, tzinfo=UTC)) == []


class TestResumeWindowIndex:
    window_a = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 14, tzinfo=UTC))
    window_b = (datetime(2026, 2, 14, tzinfo=UTC), datetime(2026, 3, 30, tzinfo=UTC))

    def test_no_bookmark_is_none(self) -> None:
        assert _resume_window_index([self.window_a, self.window_b], None) is None

    def test_matching_bookmark_returns_its_index(self) -> None:
        resume = ImpactPartnerResumeConfig(page=3, window_start=self.window_b[0].isoformat())
        assert _resume_window_index([self.window_a, self.window_b], resume) == 1

    def test_stale_bookmark_is_none(self) -> None:
        resume = ImpactPartnerResumeConfig(page=3, window_start="2020-01-01T00:00:00+00:00")
        assert _resume_window_index([self.window_a, self.window_b], resume) is None


class TestGetRowsSimple:
    def test_multi_page_endpoint_saves_state_per_page(self) -> None:
        manager = FakeResumableManager()
        responses = [
            {"Campaigns": [{"CampaignId": "1"}], "@numpages": "2"},
            {"Campaigns": [{"CampaignId": "2"}], "@numpages": "2"},
        ]
        with (
            patch.object(impact_partner, "_get_session"),
            patch.object(impact_partner, "_fetch", side_effect=responses),
        ):
            batches = list(get_rows("sid", "token", "Campaigns", API_VERSION, MagicMock(), manager))  # type: ignore[arg-type]
        assert batches == [[{"CampaignId": "1"}], [{"CampaignId": "2"}]]
        assert [s.page for s in manager.saved] == [1, 2]

    def test_resume_starts_at_saved_page(self) -> None:
        manager = FakeResumableManager(state=ImpactPartnerResumeConfig(page=2))
        with (
            patch.object(impact_partner, "_get_session"),
            patch.object(impact_partner, "_fetch", return_value={"Campaigns": [], "@numpages": "2"}) as mock_fetch,
        ):
            list(get_rows("sid", "token", "Campaigns", API_VERSION, MagicMock(), manager))  # type: ignore[arg-type]
        assert mock_fetch.call_args.args[3]["Page"] == 2

    def test_invoices_incremental_param_sent(self) -> None:
        manager = FakeResumableManager()
        with (
            patch.object(impact_partner, "_get_session"),
            patch.object(impact_partner, "_fetch", return_value={"Invoices": [], "@numpages": "1"}) as mock_fetch,
        ):
            list(
                get_rows(
                    "sid",
                    "token",
                    "Invoices",
                    API_VERSION,
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value="2026-01-01T00:00:00",
                )
            )
        assert mock_fetch.call_args.args[3]["StartDate"] == "2026-01-01T00:00:00Z"

    def test_no_incremental_param_when_not_incremental(self) -> None:
        manager = FakeResumableManager()
        with (
            patch.object(impact_partner, "_get_session"),
            patch.object(impact_partner, "_fetch", return_value={"Invoices": [], "@numpages": "1"}) as mock_fetch,
        ):
            list(get_rows("sid", "token", "Invoices", API_VERSION, MagicMock(), manager))  # type: ignore[arg-type]
        assert "StartDate" not in mock_fetch.call_args.args[3]


class TestGetRowsActions:
    @freeze_time("2026-06-01")
    def test_windows_walked_with_paired_date_params_and_no_campaign_filter(self) -> None:
        manager = FakeResumableManager()
        seen_params: list[dict[str, Any]] = []

        def fake_fetch(session: Any, account_sid: str, path: str, params: Any, logger: Any) -> Any:
            assert path == "/Actions"
            seen_params.append(params)
            return {"Actions": [{"Id": f"a{len(seen_params)}"}], "@numpages": "1"}

        with (
            patch.object(impact_partner, "_get_session"),
            patch.object(impact_partner, "_fetch", side_effect=fake_fetch),
        ):
            # A cursor 60 days back spans two 44-day windows.
            batches = list(
                get_rows(
                    "sid",
                    "token",
                    "Actions",
                    API_VERSION,
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 4, 2, tzinfo=UTC),
                )
            )

        assert len(batches) == 2
        starts = [params["ActionDateStart"] for params in seen_params]
        assert starts == sorted(starts)
        for params in seen_params:
            assert "ActionDateEnd" in params
            assert "CampaignId" not in params
        # One save per page, each bookmarking its window.
        assert [(s.window_start is not None, s.page) for s in manager.saved] == [(True, 1), (True, 1)]

    @freeze_time("2026-06-01")
    def test_resume_skips_earlier_windows_and_starts_at_saved_page(self) -> None:
        # Recompute the window grid the run will see, then bookmark the second window at page 2.
        cursor = datetime(2026, 4, 2, tzinfo=UTC)
        windows = _windows_for_actions(True, cursor)
        assert len(windows) == 2
        manager = FakeResumableManager(state=ImpactPartnerResumeConfig(page=2, window_start=windows[1][0].isoformat()))
        seen: list[tuple[str, int]] = []

        def fake_fetch(session: Any, account_sid: str, path: str, params: Any, logger: Any) -> Any:
            seen.append((params["ActionDateStart"], params["Page"]))
            return {"Actions": [], "@numpages": "2"}

        with (
            patch.object(impact_partner, "_get_session"),
            patch.object(impact_partner, "_fetch", side_effect=fake_fetch),
        ):
            list(
                get_rows(
                    "sid",
                    "token",
                    "Actions",
                    API_VERSION,
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=cursor,
                )
            )

        # Only the bookmarked window is fetched, from its saved page onward.
        assert seen == [(impact_partner._format_datetime(windows[1][0]), 2)]

    @freeze_time("2026-06-01")
    def test_stale_bookmark_restarts_from_the_first_window(self) -> None:
        manager = FakeResumableManager(
            state=ImpactPartnerResumeConfig(page=5, window_start="2020-01-01T00:00:00+00:00")
        )
        seen_pages: list[int] = []

        def fake_fetch(session: Any, account_sid: str, path: str, params: Any, logger: Any) -> Any:
            seen_pages.append(params["Page"])
            return {"Actions": [], "@numpages": "1"}

        with (
            patch.object(impact_partner, "_get_session"),
            patch.object(impact_partner, "_fetch", side_effect=fake_fetch),
        ):
            list(
                get_rows(
                    "sid",
                    "token",
                    "Actions",
                    API_VERSION,
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 5, 31, tzinfo=UTC),
                )
            )

        assert seen_pages == [1]


class TestImpactPartnerSourceResponse:
    @parameterized.expand(
        [
            ("Campaigns", ["CampaignId"], None),
            ("Actions", ["Id"], "EventDate"),
            ("Invoices", ["Id"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, expected_pks: list[str], partition_key: Optional[str]) -> None:
        response = impact_partner_source("sid", "token", endpoint, API_VERSION, MagicMock(), FakeResumableManager())  # type: ignore[arg-type]
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.partition_format == "month"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
