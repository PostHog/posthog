from typing import Any, cast

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from products.marketing_analytics.backend.services.attribution_health import (
    AttributionHealthEntry,
    AttributionHealthResponse,
)
from products.marketing_analytics.backend.services.conversion_goals_inspector import (
    ConversionGoalsListResponse,
    ConversionGoalSummary,
)
from products.marketing_analytics.backend.services.data_source_health import (
    DataSourceHealthEntry,
    DataSourceHealthResponse,
)
from products.marketing_analytics.backend.services.marketing_diagnostic import (
    _compute_overall_status,
    _diagnose_one,
    get_marketing_diagnostic,
)


def _ds_entry(**kwargs: Any) -> DataSourceHealthEntry:
    defaults: dict[str, Any] = {
        "source_type": "GoogleAds",
        "is_native": True,
        "display_name": "Google Ads",
        "connected": True,
        "last_sync_at": None,
        "last_sync_status": "ok",
        "last_error": None,
        "rows_last_24h": 100,
        "rows_last_7d": 500,
        "sources_map_present": True,
        "schema_columns_mapped": ["campaign", "source", "cost", "date"],
        "schema_columns_required_missing": [],
        "required_tables": [],
        "settings_url": "/settings/environment-marketing-analytics#marketing-settings",
        "schemas_url": "/data-management/sources/managed-fake/schemas",
        "diagnosis": "Google Ads is healthy.",
        "fix_suggestion": None,
    }
    defaults.update(kwargs)
    return DataSourceHealthEntry(**defaults)


def _attr_entry(**kwargs: Any) -> AttributionHealthEntry:
    defaults: dict[str, Any] = {
        "integration_key": "google_ads",
        "display_name": "Google Ads",
        "events_with_utm_last_7d": 1000,
        "events_matched_last_7d": 500,
        "events_unmatched_likely_yours_last_7d": 0,
        "last_event_with_matching_utm_at": None,
        "matched_pct": 50.0,
        "sample_unmatched_utm_sources": [],
    }
    defaults.update(kwargs)
    return AttributionHealthEntry(**defaults)


_DIAGNOSE_ONE_CASES: list[tuple[str, dict | None, dict | None, str, str | None]] = [
    # name, ds_kwargs (None → no source), attr_kwargs (None → no attribution),
    # expected_status, expected_action_target_tool (None when no specific tool action)
    ("not_connected_no_signals", None, None, "not_connected", None),
    ("events_only_when_matched_no_source", None, {"events_matched_last_7d": 200}, "events_only", None),
    (
        "sync_broken_on_error",
        {"last_sync_status": "error", "last_error": "auth", "diagnosis": "Google Ads last sync failed."},
        {},
        "sync_broken",
        None,
    ),
    ("sync_broken_on_stale", {"last_sync_status": "stale"}, {}, "sync_broken", None),
    ("schema_misconfigured", {"schema_columns_required_missing": ["cost"]}, {}, "schema_misconfigured", None),
    (
        "events_unmatched_with_likely_yours",
        {},
        {"events_matched_last_7d": 0, "events_unmatched_likely_yours_last_7d": 300},
        "events_unmatched",
        "marketing_suggest_utm_mappings",
    ),
    (
        "events_broken_when_sync_ok_no_events",
        {},
        {"events_matched_last_7d": 0, "events_unmatched_likely_yours_last_7d": 0},
        "events_broken",
        "marketing_audit_utm",
    ),
    ("healthy_when_sync_ok_and_matched", {}, {"events_matched_last_7d": 500}, "healthy", None),
]


class TestDiagnoseOne:
    @parameterized.expand([(case[0], *case[1:]) for case in _DIAGNOSE_ONE_CASES])
    def test_diagnose_one(self, _name, ds_kwargs, attr_kwargs, expected_status, expected_target_tool):
        ds = _ds_entry(**ds_kwargs) if ds_kwargs is not None else None
        attr = _attr_entry(**attr_kwargs) if attr_kwargs is not None else None
        result = _diagnose_one("GoogleAds", "google_ads", ds=ds, attr=attr)
        assert result.overall_status == expected_status
        if expected_target_tool is None:
            return
        assert any(a.target_tool == expected_target_tool for a in result.recommended_actions)


def _make_diag(status: str):
    from products.marketing_analytics.backend.services.marketing_diagnostic import (
        IntegrationDiagnostic,
        IntegrationStatus,
    )

    return IntegrationDiagnostic(
        integration_key="google_ads",
        source_type="GoogleAds",
        display_name="Google Ads",
        overall_status=cast(IntegrationStatus, status),
        diagnosis="",
        data_source=None,
        attribution=None,
    )


class TestComputeOverallStatus:
    @parameterized.expand(
        [
            ("only_not_connected_is_no_sources", ["not_connected", "not_connected"], "no_sources"),
            ("all_healthy_is_healthy", ["healthy", "healthy"], "healthy"),
            ("mixed_healthy_and_problems_is_degraded", ["healthy", "events_unmatched"], "degraded"),
            ("only_sync_broken_is_broken", ["sync_broken", "schema_misconfigured"], "broken"),
            ("events_unmatched_alone_is_degraded_not_broken", ["events_unmatched"], "degraded"),
        ]
    )
    def test_compute_overall_status(self, _name, statuses, expected):
        diags = [_make_diag(s) for s in statuses]
        assert _compute_overall_status(diags) == expected


class TestGetMarketingDiagnostic(APIBaseTest):
    def setUp(self):
        super().setUp()
        ds_patcher = patch(
            "products.marketing_analytics.backend.services.marketing_diagnostic.get_data_source_health",
            new_callable=AsyncMock,
        )
        attr_patcher = patch(
            "products.marketing_analytics.backend.services.marketing_diagnostic.get_attribution_health",
            new_callable=AsyncMock,
        )
        goals_patcher = patch(
            "products.marketing_analytics.backend.services.marketing_diagnostic.list_conversion_goals",
            new_callable=AsyncMock,
        )
        config_patcher = patch(
            "products.marketing_analytics.backend.services.marketing_diagnostic._load_marketing_config_snapshot",
            new_callable=AsyncMock,
        )
        self.mock_ds = ds_patcher.start()
        self.mock_attr = attr_patcher.start()
        self.mock_goals = goals_patcher.start()
        self.mock_config = config_patcher.start()
        self.addCleanup(ds_patcher.stop)
        self.addCleanup(attr_patcher.stop)
        self.addCleanup(goals_patcher.stop)
        self.addCleanup(config_patcher.stop)

        self.mock_ds.return_value = DataSourceHealthResponse(
            integrations=[], has_any_data=False, overall_status="no_sources"
        )
        self.mock_attr.return_value = AttributionHealthResponse(lookback_days=7)
        self.mock_goals.return_value = ConversionGoalsListResponse()
        self.mock_config.return_value = ({}, {})

    @pytest.mark.asyncio
    async def test_no_sources_no_events_no_goals(self):
        response = await get_marketing_diagnostic(self.team)
        assert response.overall_status == "no_sources"
        assert "No marketing integrations" in response.summary
        # Encourages configuring goals when none exist.
        assert any(a.target_tool == "marketing_suggest_conversion_goals" for a in response.recommended_actions)

    @pytest.mark.asyncio
    async def test_events_only_corner_case_surfaced(self):
        self.mock_attr.return_value = AttributionHealthResponse(
            lookback_days=7,
            integrations=[_attr_entry(events_matched_last_7d=100)],
        )

        response = await get_marketing_diagnostic(self.team)
        google = next(i for i in response.integrations if i.integration_key == "google_ads")
        assert google.overall_status == "events_only"

    @pytest.mark.asyncio
    async def test_sync_broken_propagates_to_overall(self):
        self.mock_ds.return_value = DataSourceHealthResponse(
            integrations=[_ds_entry(last_sync_status="error", last_error="x")],
            has_any_data=False,
            overall_status="broken",
        )
        response = await get_marketing_diagnostic(self.team)
        assert response.overall_status == "broken"

    @pytest.mark.asyncio
    async def test_misconfigured_goals_surface_in_global_actions(self):
        goal = ConversionGoalSummary(
            id="999",
            name="Sign up",
            kind="ActionsNode",
            target_label="Action #999",
            last_30d_count=0,
            integrated_count=None,
            events_without_utm_source=None,
            events_with_unmatched_utm_source=None,
            non_integrated_count=None,
            integrated_pct=None,
            is_misconfigured=True,
            misconfig_reason="Action 999 does not exist",
        )
        self.mock_goals.return_value = ConversionGoalsListResponse(
            goals=[goal], attribution_window_days=90, attribution_mode="last_touch", has_misconfigured=True
        )
        response = await get_marketing_diagnostic(self.team)
        assert any("misconfigured conversion goal" in a.title for a in response.recommended_actions)

    @pytest.mark.asyncio
    async def test_summary_mentions_healthy_count(self):
        self.mock_ds.return_value = DataSourceHealthResponse(
            integrations=[_ds_entry()],
            has_any_data=True,
            overall_status="healthy",
        )
        self.mock_attr.return_value = AttributionHealthResponse(
            lookback_days=7,
            integrations=[_attr_entry(events_matched_last_7d=500)],
        )
        response = await get_marketing_diagnostic(self.team)
        assert response.overall_status == "healthy"
        assert "healthy" in response.summary

    @pytest.mark.asyncio
    async def test_include_conversion_goals_false_skips_goals_call(self):
        await get_marketing_diagnostic(self.team, include_conversion_goals=False)
        self.mock_goals.assert_not_awaited()
