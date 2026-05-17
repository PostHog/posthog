from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from products.marketing_analytics.backend.services.data_source_health import (
    STALE_THRESHOLD,
    DataSourceHealthEntry,
    _build_issues_summary,
    _compute_overall_status,
    _resolve_sync_status,
    get_data_source_health,
)


class TestResolveSyncStatus:
    def test_never_synced_returns_never(self):
        assert _resolve_sync_status(last_completed_at=None, last_error_text=None, required_tables=[]) == "never"

    def test_recent_completed_returns_ok(self):
        assert (
            _resolve_sync_status(
                last_completed_at=timezone.now() - timedelta(minutes=10), last_error_text=None, required_tables=[]
            )
            == "ok"
        )

    def test_old_completed_returns_stale(self):
        assert (
            _resolve_sync_status(
                last_completed_at=timezone.now() - STALE_THRESHOLD - timedelta(minutes=1),
                last_error_text=None,
                required_tables=[],
            )
            == "stale"
        )

    def test_error_text_takes_priority_over_completed(self):
        assert (
            _resolve_sync_status(
                last_completed_at=timezone.now() - timedelta(minutes=10), last_error_text="boom", required_tables=[]
            )
            == "error"
        )


def _entry(**kwargs) -> DataSourceHealthEntry:
    defaults = {
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


class TestComputeOverallStatus:
    def test_no_connected_sources_is_no_sources(self):
        entries = [_entry(connected=False, last_sync_status="not_connected")]
        assert _compute_overall_status(entries) == "no_sources"

    def test_all_connected_and_ok_is_healthy(self):
        entries = [_entry(), _entry(source_type="MetaAds", display_name="Meta Ads")]
        assert _compute_overall_status(entries) == "healthy"

    def test_all_errored_is_broken(self):
        entries = [_entry(last_sync_status="error", last_error="x")]
        assert _compute_overall_status(entries) == "broken"

    def test_mixed_is_degraded(self):
        entries = [_entry(), _entry(source_type="MetaAds", last_sync_status="error")]
        assert _compute_overall_status(entries) == "degraded"

    def test_required_missing_is_degraded(self):
        entries = [_entry(schema_columns_required_missing=["campaign"])]
        assert _compute_overall_status(entries) == "degraded"


class TestBuildIssuesSummary:
    def test_only_lists_problematic_entries(self):
        ok = _entry(last_sync_status="ok", schema_columns_required_missing=[])
        broken = _entry(
            source_type="MetaAds",
            display_name="Meta Ads",
            last_sync_status="error",
            last_error="rate limit",
            diagnosis="Meta Ads last sync failed.",
        )
        summary = _build_issues_summary([ok, broken])
        assert len(summary) == 1
        assert "Meta Ads" in summary[0]

    def test_schema_missing_surfaces_in_summary_even_if_sync_ok(self):
        broken = _entry(
            source_type="MetaAds",
            display_name="Meta Ads",
            last_sync_status="ok",
            schema_columns_required_missing=["cost"],
            diagnosis="Meta Ads is syncing but required schema columns are not mapped.",
        )
        summary = _build_issues_summary([broken])
        assert len(summary) == 1
        assert "Meta Ads" in summary[0]


class _FakeSource:
    def __init__(self, source_id: str = "src-uuid-1", source_type: str = "GoogleAds"):
        self.id = source_id
        self.source_type = source_type


class TestGetDataSourceHealthOrchestration(APIBaseTest):
    def setUp(self):
        super().setUp()
        _TARGETS = {
            "sources_map": "products.marketing_analytics.backend.services.data_source_health._get_sources_map",
            "sources_by_type": "products.marketing_analytics.backend.services.data_source_health._get_sources_by_type",
            "last_job_state": "products.marketing_analytics.backend.services.data_source_health._get_last_job_state",
            "rows_synced": "products.marketing_analytics.backend.services.data_source_health._get_rows_synced",
            "required_tables": "products.marketing_analytics.backend.services.data_source_health._get_required_tables_status",
        }
        patchers = {key: patch(target, new_callable=AsyncMock) for key, target in _TARGETS.items()}
        self.mocks = {key: p.start() for key, p in patchers.items()}
        for p in patchers.values():
            self.addCleanup(p.stop)

        # Defaults: empty config, no sources, never synced, no rows, no required tables.
        self.mocks["sources_map"].return_value = {}
        self.mocks["sources_by_type"].return_value = {}
        self.mocks["last_job_state"].return_value = (None, None)
        self.mocks["rows_synced"].return_value = (0, 0)
        self.mocks["required_tables"].return_value = []

    @pytest.mark.asyncio
    async def test_no_sources_returns_no_sources_status(self):
        response = await get_data_source_health(self.team)
        assert response.overall_status == "no_sources"
        assert response.has_any_data is False
        assert all(e.connected is False for e in response.integrations)
        assert all(e.last_sync_status == "not_connected" for e in response.integrations)

    @pytest.mark.asyncio
    async def test_native_source_with_recent_sync_is_ok(self):
        self.mocks["sources_by_type"].return_value = {"GoogleAds": _FakeSource()}
        self.mocks["last_job_state"].return_value = (timezone.now() - timedelta(minutes=15), None)
        self.mocks["rows_synced"].return_value = (500, 500)
        self.mocks["sources_map"].return_value = {
            "src-uuid-1": {"campaign": "name", "source": "src", "cost": "spend", "date": "day"}
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
        self.mocks["sources_by_type"].return_value = {"BingAds": _FakeSource(source_type="BingAds")}
        self.mocks["last_job_state"].return_value = (None, "auth failed")

        response = await get_data_source_health(self.team, source_type="BingAds")

        assert len(response.integrations) == 1
        assert response.integrations[0].last_sync_status == "error"
        assert response.integrations[0].last_error == "auth failed"

    @pytest.mark.asyncio
    async def test_stale_completed_is_marked_stale(self):
        self.mocks["sources_by_type"].return_value = {"MetaAds": _FakeSource(source_type="MetaAds")}
        self.mocks["last_job_state"].return_value = (timezone.now() - STALE_THRESHOLD - timedelta(hours=1), None)

        response = await get_data_source_health(self.team, source_type="MetaAds")

        assert response.integrations[0].last_sync_status == "stale"

    @pytest.mark.asyncio
    async def test_filter_by_source_type_returns_only_that_one(self):
        self.mocks["sources_by_type"].return_value = {"GoogleAds": _FakeSource()}

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
        self.mocks["sources_by_type"].return_value = {"GoogleAds": _FakeSource()}
        self.mocks["last_job_state"].return_value = (timezone.now() - timedelta(minutes=5), None)
        self.mocks["sources_map"].return_value = {"src-uuid-1": {"campaign": "name"}}

        response = await get_data_source_health(self.team, source_type="GoogleAds")

        entry = response.integrations[0]
        assert entry.schema_columns_required_missing == []
