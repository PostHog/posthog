from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.marketing_analytics.backend.services.data_source_health import (
    STALE_THRESHOLD,
    DataSourceHealthEntry,
    _build_issues_summary,
    _compute_overall_status,
    get_data_source_health,
)
from products.warehouse_sources.backend.facade import contracts as warehouse_contracts

# Sync-status resolution (never/ok/stale/error/tables_*) now lives in the warehouse
# facade — decision-table coverage is in the facade's own tests. These tests cover
# the marketing product layer: entry building, filtering, and overall status.


def _entry(**kwargs: Any) -> DataSourceHealthEntry:
    defaults: dict[str, Any] = {
        "source_type": "GoogleAds",
        "is_native": True,
        "display_name": "Google Ads",
        "connected": True,
        "last_sync_at": None,
        "last_sync_status": "ok",
        "last_error": None,
        "rows_last_24h": 0,
        "rows_last_7d": 0,
        "sources_map_present": True,
        "schema_columns_mapped": ["campaign", "source", "cost", "date"],
        "schema_columns_required_missing": [],
        "required_tables": [],
        "settings_url": "/settings/environment-marketing-analytics#marketing-settings",
        "schemas_url": None,
        "diagnosis": "ok",
        "fix_suggestion": None,
    }
    defaults.update(kwargs)
    return DataSourceHealthEntry(**defaults)


def _entries_for_status_test(case_name: str) -> list[DataSourceHealthEntry]:
    if case_name == "no_connected":
        return [_entry(connected=False, last_sync_status="not_connected")]
    if case_name == "all_ok":
        return [_entry(), _entry(source_type="MetaAds", display_name="Meta Ads")]
    if case_name == "all_errored":
        return [_entry(last_sync_status="error", last_error="x")]
    if case_name == "mixed":
        return [_entry(), _entry(source_type="MetaAds", last_sync_status="error")]
    if case_name == "required_missing":
        return [_entry(schema_columns_required_missing=["campaign"])]
    raise ValueError(f"unknown case: {case_name}")


class TestComputeOverallStatus:
    @parameterized.expand(
        [
            ("no_connected_sources_is_no_sources", "no_connected", "no_sources"),
            ("all_connected_and_ok_is_healthy", "all_ok", "healthy"),
            ("all_errored_is_broken", "all_errored", "broken"),
            ("mixed_is_degraded", "mixed", "degraded"),
            ("required_missing_is_degraded", "required_missing", "degraded"),
        ]
    )
    def test_compute_overall_status(self, _name, case_name, expected):
        entries = _entries_for_status_test(case_name)
        assert _compute_overall_status(entries) == expected


class TestBuildIssuesSummary:
    @parameterized.expand(
        [
            (
                "only_lists_problematic_entries",
                [
                    _entry(last_sync_status="ok", schema_columns_required_missing=[]),
                    _entry(
                        source_type="MetaAds",
                        display_name="Meta Ads",
                        last_sync_status="error",
                        last_error="rate limit",
                        diagnosis="Meta Ads last sync failed.",
                    ),
                ],
                1,
                "Meta Ads",
            ),
            (
                "schema_missing_surfaces_in_summary_even_if_sync_ok",
                [
                    _entry(
                        source_type="MetaAds",
                        display_name="Meta Ads",
                        last_sync_status="ok",
                        schema_columns_required_missing=["cost"],
                        diagnosis="Meta Ads is syncing but required schema columns are not mapped.",
                    ),
                ],
                1,
                "Meta Ads",
            ),
        ]
    )
    def test_build_issues_summary(
        self,
        _name: str,
        entries: list[DataSourceHealthEntry],
        expected_count: int,
        expected_substring: str,
    ) -> None:
        summary = _build_issues_summary(entries)
        assert len(summary) == expected_count
        assert expected_substring in summary[0]


_SRC_ID = UUID("12345678-1234-5678-1234-567812345678")


def _health(
    source_type: str = "GoogleAds",
    sync_status: str = "ok",
    *,
    last_completed_sync_at: datetime | None = None,
    last_unresolved_error: str | None = None,
    rows_24h: int = 0,
    rows_7d: int = 0,
) -> warehouse_contracts.SourceHealth:
    return warehouse_contracts.SourceHealth(
        source_id=_SRC_ID,
        team_id=1,
        source_type=source_type,
        prefix=None,
        created_at=timezone.now(),
        sync_status=sync_status,  # type: ignore[arg-type]
        last_completed_sync_at=last_completed_sync_at,
        last_unresolved_error=last_unresolved_error,
        rows_synced_last_24h=rows_24h,
        rows_synced_last_7d=rows_7d,
        schemas=[],
    )


@freeze_time("2025-06-15")
class TestGetDataSourceHealthOrchestration(APIBaseTest):
    def setUp(self):
        super().setUp()
        _TARGETS = {
            "sources_map": "products.marketing_analytics.backend.services.data_source_health._get_sources_map",
            "health_by_type": "products.marketing_analytics.backend.services.data_source_health._get_health_by_type",
        }
        patchers = {key: patch(target, new_callable=AsyncMock) for key, target in _TARGETS.items()}
        self.mocks = {key: p.start() for key, p in patchers.items()}
        for p in patchers.values():
            self.addCleanup(p.stop)

        # Defaults: empty config, no connected sources.
        self.mocks["sources_map"].return_value = {}
        self.mocks["health_by_type"].return_value = {}

    @pytest.mark.asyncio
    async def test_no_sources_returns_no_sources_status(self):
        response = await get_data_source_health(self.team)
        assert response.overall_status == "no_sources"
        assert response.has_any_data is False
        assert all(e.connected is False for e in response.integrations)
        assert all(e.last_sync_status == "not_connected" for e in response.integrations)

    @pytest.mark.asyncio
    async def test_native_source_with_recent_sync_is_ok(self):
        self.mocks["health_by_type"].return_value = {
            "GoogleAds": _health(
                sync_status="ok",
                last_completed_sync_at=timezone.now() - timedelta(minutes=15),
                rows_24h=500,
                rows_7d=500,
            )
        }
        self.mocks["sources_map"].return_value = {
            str(_SRC_ID): {"campaign": "name", "source": "src", "cost": "spend", "date": "day"}
        }

        response = await get_data_source_health(self.team)

        google = next(e for e in response.integrations if e.source_type == "GoogleAds")
        assert google.connected is True
        assert google.last_sync_status == "ok"
        assert google.rows_last_24h == 500
        assert google.schema_columns_required_missing == []
        assert response.has_any_data is True

    @pytest.mark.asyncio
    async def test_failed_job_text_surfaces_as_error_status(self):
        self.mocks["health_by_type"].return_value = {
            "BingAds": _health(source_type="BingAds", sync_status="error", last_unresolved_error="auth failed")
        }

        response = await get_data_source_health(self.team, source_type="BingAds")

        assert len(response.integrations) == 1
        assert response.integrations[0].last_sync_status == "error"
        assert response.integrations[0].last_error == "auth failed"

    @pytest.mark.asyncio
    async def test_stale_status_passes_through_to_entry(self):
        self.mocks["health_by_type"].return_value = {
            "MetaAds": _health(
                source_type="MetaAds",
                sync_status="stale",
                last_completed_sync_at=timezone.now() - STALE_THRESHOLD - timedelta(hours=1),
            )
        }

        response = await get_data_source_health(self.team, source_type="MetaAds")

        assert response.integrations[0].last_sync_status == "stale"

    @pytest.mark.asyncio
    async def test_filter_by_source_type_returns_only_that_one(self):
        self.mocks["health_by_type"].return_value = {"GoogleAds": _health()}

        response = await get_data_source_health(self.team, source_type="GoogleAds")

        assert len(response.integrations) == 1
        assert response.integrations[0].source_type == "GoogleAds"

    @pytest.mark.asyncio
    async def test_unknown_source_type_filter_returns_empty(self):
        response = await get_data_source_health(self.team, source_type="DefinitelyNotASource")
        assert response.integrations == []

    @pytest.mark.asyncio
    async def test_native_sources_never_report_missing_columns(self):
        # Native sources (Google Ads, Meta, etc.) don't require column mapping —
        # the column → field map is implicit in the platform's API. Only self-managed
        # sources (BigQuery, S3) need explicit column mapping. So for a native source,
        # `schema_columns_required_missing` must always be empty regardless of
        # `sources_map` content.
        self.mocks["health_by_type"].return_value = {
            "GoogleAds": _health(last_completed_sync_at=timezone.now() - timedelta(minutes=5))
        }
        self.mocks["sources_map"].return_value = {str(_SRC_ID): {"campaign": "name"}}

        response = await get_data_source_health(self.team, source_type="GoogleAds")

        entry = response.integrations[0]
        assert entry.schema_columns_required_missing == []
