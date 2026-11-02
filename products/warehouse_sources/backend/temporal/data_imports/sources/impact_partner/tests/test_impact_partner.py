from datetime import UTC, datetime
from typing import Optional

import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.impactpartner import (
    ImpactPartnerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.impact_partner.impact_partner import (
    ImpactPartnerResumeConfig,
    _windows_for_actions,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.impact_partner.source import ImpactPartnerSource

API_VERSION = "16"


def _driver() -> SourceDriver:
    return SourceDriver(ImpactPartnerSource(), ImpactPartnerSourceConfig(account_sid="sid", auth_token="token"))


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("sid", "token", API_VERSION) is expected

        assert network.requests_log[0].path == "/Mediapartners/sid/Campaigns"
        assert network.requests_log[0].param("PageSize") == "1"
        assert network.requests_log[0].headers["ir-version"] == API_VERSION


class TestWindowsForActions:
    @time_machine.travel("2026-06-01", tick=False)
    def test_full_refresh_backfills_max_lookback(self) -> None:
        windows = _windows_for_actions(False, None)
        assert windows[0][0] == datetime(2023, 6, 2, tzinfo=UTC)
        assert windows[-1][1] == datetime(2026, 6, 1, tzinfo=UTC)

    @time_machine.travel("2026-06-01", tick=False)
    def test_future_cursor_yields_no_windows(self) -> None:
        assert _windows_for_actions(True, datetime(2027, 1, 1, tzinfo=UTC)) == []


class TestGetRowsSimple:
    def test_multi_page_endpoint_saves_state_per_page(self) -> None:
        result = _driver().run(
            "Campaigns",
            [
                ScriptedResponse(json={"Campaigns": [{"CampaignId": "1"}], "@numpages": "2"}),
                ScriptedResponse(json={"Campaigns": [{"CampaignId": "2"}], "@numpages": "2"}),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"CampaignId": "1"}], [{"CampaignId": "2"}]]
        assert result.paths == ["/Mediapartners/sid/Campaigns"] * 2
        assert result.params("Page") == ["1", "2"]
        assert result.saved_states == [ImpactPartnerResumeConfig(page=1), ImpactPartnerResumeConfig(page=2)]

    def test_invoices_incremental_param_sent(self) -> None:
        result = _driver().run(
            "Invoices",
            [ScriptedResponse(json={"Invoices": [], "@numpages": "1"})],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00",
        )

        assert result.raised is None
        assert result.requests[0].param("StartDate") == "2026-01-01T00:00:00Z"


class TestGetRowsActions:
    @time_machine.travel("2026-06-01", tick=False)
    def test_windows_walked_with_paired_date_params_and_no_campaign_filter(self) -> None:
        # A cursor 60 days back spans two 44-day windows.
        result = _driver().run(
            "Actions",
            always(ScriptedResponse(json={"Actions": [{"Id": "a1"}], "@numpages": "1"})),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 4, 2, tzinfo=UTC),
        )

        assert result.raised is None
        assert len(result.items) == 2
        starts = result.params("ActionDateStart")
        assert starts == sorted(starts, key=lambda value: value or "")
        for request in result.requests:
            assert request.path == "/Mediapartners/sid/Actions"
            assert request.param("ActionDateEnd") is not None
            assert request.param("CampaignId") is None
        # One save per page, each bookmarking its window.
        assert [(state.window_start is not None, state.page) for state in result.saved_states] == [
            (True, 1),
            (True, 1),
        ]

    @time_machine.travel("2026-06-01", tick=False)
    def test_resume_skips_earlier_windows_and_starts_at_saved_page(self) -> None:
        # Recompute the window grid the run will see, then bookmark the second window at page 2.
        cursor = datetime(2026, 4, 2, tzinfo=UTC)
        windows = _windows_for_actions(True, cursor)
        assert len(windows) == 2
        result = _driver().run(
            "Actions",
            [ScriptedResponse(json={"Actions": [], "@numpages": "2"})],
            resume_state=ImpactPartnerResumeConfig(page=2, window_start=windows[1][0].isoformat()),
            should_use_incremental_field=True,
            db_incremental_field_last_value=cursor,
        )

        # Only the bookmarked window is fetched, from its saved page onward.
        assert result.raised is None
        assert result.params("ActionDateStart") == ["2026-05-16T00:00:00Z"]
        assert result.params("Page") == ["2"]

    @time_machine.travel("2026-06-01", tick=False)
    def test_stale_bookmark_restarts_from_the_first_window(self) -> None:
        result = _driver().run(
            "Actions",
            [ScriptedResponse(json={"Actions": [], "@numpages": "1"})],
            resume_state=ImpactPartnerResumeConfig(page=5, window_start="2020-01-01T00:00:00+00:00"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 5, 31, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("Page") == ["1"]


class TestImpactPartnerSourceResponse:
    @parameterized.expand(
        [
            ("Campaigns", ["CampaignId"], None),
            ("Actions", ["Id"], "EventDate"),
            ("Invoices", ["Id"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, expected_pks: list[str], partition_key: Optional[str]) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={endpoint: [], "@numpages": "1"})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(9999, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.partition_format == "month"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
