"""Tests for the project profile tools and inventory aggregator.

Layered top-down: builder source-readers → `compute_project_profile` end-to-end →
`get_project_profile` cache-hit / cache-miss paths.
"""

from __future__ import annotations

from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.insight import Insight, InsightViewed
from posthog.models.integration import Integration
from posthog.models.product_intent.product_intent import ProductIntent

from products.dashboards.backend.models.dashboard import Dashboard
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.signals.backend.agent_harness.profile import INVENTORY_SOURCE_VERSION, build_inventory
from products.signals.backend.agent_harness.profile.builders import (
    _existing_inbox_reports,
    _external_data_sources,
    _integrations,
    _popular_insights,
    _product_intents,
    _products_in_use,
    _project_context,
    _recent_dashboards,
    _signal_source_configs,
)
from products.signals.backend.agent_harness.tools.profile import (
    PROFILE_TTL,
    compute_project_profile,
    get_project_profile,
)
from products.signals.backend.models import SignalProjectProfile, SignalReport, SignalSourceConfig


class TestProjectContext(BaseTest):
    def test_returns_product_description_and_app_urls(self) -> None:
        self.team.app_urls = ["https://app.example.com", "https://docs.example.com"]
        self.team.save()
        self.team.project.product_description = "A demo SaaS for testing"
        self.team.project.save()
        result = _project_context(self.team)
        assert result == {
            "product_description": "A demo SaaS for testing",
            "app_urls": ["https://app.example.com", "https://docs.example.com"],
        }

    def test_null_product_description_when_unset(self) -> None:
        self.team.project.product_description = None
        self.team.project.save()
        self.team.app_urls = []
        self.team.save()
        result = _project_context(self.team)
        assert result == {"product_description": None, "app_urls": []}

    def test_strips_blank_product_description(self) -> None:
        # A blank-string description should surface as null so the agent doesn't read
        # an empty string as "I have a product description, it's just empty."
        self.team.project.product_description = "   "
        self.team.project.save()
        result = _project_context(self.team)
        assert result["product_description"] is None

    def test_filters_empty_app_urls(self) -> None:
        self.team.app_urls = ["https://app.example.com", "", None]  # type: ignore[list-item]
        self.team.save()
        result = _project_context(self.team)
        assert result["app_urls"] == ["https://app.example.com"]


class TestProductsInUse(BaseTest):
    def test_returns_keys_with_truthy_values_sorted(self) -> None:
        self.team.has_completed_onboarding_for = {"product_analytics": True, "session_replay": True, "surveys": False}
        self.team.save()
        assert _products_in_use(self.team) == ["product_analytics", "session_replay"]

    def test_empty_when_field_is_null(self) -> None:
        self.team.has_completed_onboarding_for = None
        self.team.save()
        assert _products_in_use(self.team) == []

    def test_handles_non_dict_field_gracefully(self) -> None:
        # Defensive: if the JSON field somehow holds a non-dict value, return [] rather than raise.
        self.team.has_completed_onboarding_for = ["product_analytics"]  # type: ignore[assignment]
        self.team.save()
        assert _products_in_use(self.team) == []


class TestProductIntents(BaseTest):
    def test_returns_intents_for_team_only(self) -> None:
        ProductIntent.objects.create(team=self.team, product_type="error_tracking")
        # Other team's intent should not appear.
        other = self.organization.teams.create(name="other")
        ProductIntent.objects.create(team=other, product_type="data_warehouse")
        result = _product_intents(self.team)
        assert [r["product_type"] for r in result] == ["error_tracking"]

    def test_carries_activated_at_when_set(self) -> None:
        intent = ProductIntent.objects.create(team=self.team, product_type="experiments")
        when = timezone.now()
        ProductIntent.objects.filter(id=intent.id).update(activated_at=when)
        result = _product_intents(self.team)
        assert result[0]["activated_at"] is not None


class TestIntegrations(BaseTest):
    def test_lists_integrations_by_kind(self) -> None:
        Integration.objects.create(team=self.team, kind="github", config={})
        Integration.objects.create(team=self.team, kind="slack", config={})
        result = _integrations(self.team)
        assert sorted(r["kind"] for r in result) == ["github", "slack"]

    def test_does_not_leak_config_or_sensitive_config(self) -> None:
        # Defensive: integration config/sensitive_config can hold tokens; only kind + created_at
        # should reach the agent.
        Integration.objects.create(
            team=self.team,
            kind="slack",
            config={"workspace_id": "T123"},
            sensitive_config={"access_token": "xoxb-secret"},
        )
        result = _integrations(self.team)
        assert "config" not in result[0]
        assert "sensitive_config" not in result[0]


class TestExternalDataSources(BaseTest):
    def test_excludes_deleted_rows(self) -> None:
        ExternalDataSource.objects.create(team=self.team, source_type="Stripe", status="Running", prefix="stripe_")
        ExternalDataSource.objects.create(
            team=self.team, source_type="Hubspot", status="Running", prefix="hub_", deleted=True
        )
        result = _external_data_sources(self.team)
        assert [r["source_type"] for r in result] == ["Stripe"]

    def test_carries_status_and_prefix(self) -> None:
        ExternalDataSource.objects.create(team=self.team, source_type="Postgres", status="Failed", prefix="pg_")
        result = _external_data_sources(self.team)
        assert result[0]["status"] == "Failed"
        assert result[0]["prefix"] == "pg_"


class TestSignalSourceConfigs(BaseTest):
    def test_splits_enabled_and_disabled(self) -> None:
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product=SignalSourceConfig.SourceProduct.ERROR_TRACKING,
            source_type=SignalSourceConfig.SourceType.ISSUE,
            enabled=True,
        )
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product=SignalSourceConfig.SourceProduct.LINEAR,
            source_type=SignalSourceConfig.SourceType.TICKET,
            enabled=False,
        )
        result = _signal_source_configs(self.team)
        assert len(result["enabled"]) == 1
        assert result["enabled"][0]["source_product"] == "error_tracking"
        assert len(result["disabled"]) == 1
        assert result["disabled"][0]["source_product"] == "linear"


class TestExistingInboxReports(BaseTest):
    def test_groups_by_status_excluding_deleted_and_suppressed(self) -> None:
        SignalReport.objects.create(team=self.team, status=SignalReport.Status.POTENTIAL)
        SignalReport.objects.create(team=self.team, status=SignalReport.Status.POTENTIAL)
        SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)
        SignalReport.objects.create(team=self.team, status=SignalReport.Status.DELETED)
        SignalReport.objects.create(team=self.team, status=SignalReport.Status.SUPPRESSED)
        result = _existing_inbox_reports(self.team)
        assert result["total"] == 3
        by_status = {row["status"]: row["count"] for row in result["by_status"]}
        assert by_status == {"potential": 2, "ready": 1}

    def test_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        SignalReport.objects.create(team=other, status=SignalReport.Status.READY)
        result = _existing_inbox_reports(self.team)
        assert result["total"] == 0


class TestRecentDashboards(BaseTest):
    def test_orders_by_last_accessed_desc(self) -> None:
        old = Dashboard.objects.create(team=self.team, name="old")
        new = Dashboard.objects.create(team=self.team, name="new")
        Dashboard.objects.filter(id=old.id).update(last_accessed_at=timezone.now() - timedelta(hours=2))
        Dashboard.objects.filter(id=new.id).update(last_accessed_at=timezone.now())
        result = _recent_dashboards(self.team)
        assert [r["name"] for r in result] == ["new", "old"]

    def test_excludes_deleted(self) -> None:
        live = Dashboard.objects.create(team=self.team, name="live")
        gone = Dashboard.objects.create(team=self.team, name="gone", deleted=True)
        Dashboard.objects.filter(id=live.id).update(last_accessed_at=timezone.now())
        Dashboard.objects.filter(id=gone.id).update(last_accessed_at=timezone.now())
        result = _recent_dashboards(self.team)
        assert [r["name"] for r in result] == ["live"]

    def test_excludes_never_accessed(self) -> None:
        # last_accessed_at null = never opened — surfacing it as "recent" would lie.
        accessed = Dashboard.objects.create(team=self.team, name="accessed")
        Dashboard.objects.filter(id=accessed.id).update(last_accessed_at=timezone.now())
        Dashboard.objects.create(team=self.team, name="never")  # last_accessed_at = null
        result = _recent_dashboards(self.team)
        assert [r["name"] for r in result] == ["accessed"]

    def test_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        d = Dashboard.objects.create(team=other, name="other-team")
        Dashboard.objects.filter(id=d.id).update(last_accessed_at=timezone.now())
        result = _recent_dashboards(self.team)
        assert result == []


class TestPopularInsights(BaseTest):
    def test_orders_by_distinct_viewer_count_desc(self) -> None:
        # Two insights with distinct viewers; popular has more.
        popular = Insight.objects.create(team=self.team, name="popular")
        niche = Insight.objects.create(team=self.team, name="niche")
        u1 = self._create_user("u1@example.com")
        u2 = self._create_user("u2@example.com")
        u3 = self._create_user("u3@example.com")
        # 3 viewers on `popular`, 1 on `niche`.
        for user in (u1, u2, u3):
            InsightViewed.objects.create(team=self.team, user=user, insight=popular, last_viewed_at=timezone.now())
        InsightViewed.objects.create(team=self.team, user=u1, insight=niche, last_viewed_at=timezone.now())
        result = _popular_insights(self.team)
        assert [r["name"] for r in result] == ["popular", "niche"]
        assert result[0]["viewer_count"] == 3
        assert result[1]["viewer_count"] == 1

    def test_excludes_never_viewed_insights(self) -> None:
        # An insight with no `InsightViewed` rows is filtered out — useless orientation.
        seen = Insight.objects.create(team=self.team, name="seen")
        Insight.objects.create(team=self.team, name="unseen")
        u1 = self._create_user("u1@example.com")
        InsightViewed.objects.create(team=self.team, user=u1, insight=seen, last_viewed_at=timezone.now())
        result = _popular_insights(self.team)
        assert [r["name"] for r in result] == ["seen"]

    def test_falls_back_to_derived_name_when_name_blank(self) -> None:
        insight = Insight.objects.create(team=self.team, name=None, derived_name="Auto-named")
        u1 = self._create_user("u1@example.com")
        InsightViewed.objects.create(team=self.team, user=u1, insight=insight, last_viewed_at=timezone.now())
        result = _popular_insights(self.team)
        assert result[0]["name"] == "Auto-named"

    def test_excludes_deleted_insights(self) -> None:
        live = Insight.objects.create(team=self.team, name="live")
        deleted = Insight.objects.create(team=self.team, name="dead", deleted=True)
        u1 = self._create_user("u1@example.com")
        for ins in (live, deleted):
            InsightViewed.objects.create(team=self.team, user=u1, insight=ins, last_viewed_at=timezone.now())
        result = _popular_insights(self.team)
        assert [r["name"] for r in result] == ["live"]

    def _create_user(self, email: str):
        from posthog.models.user import User

        return User.objects.create(email=email, distinct_id=email)


class TestBuildInventory(BaseTest):
    def test_returns_all_inventory_keys(self) -> None:
        inventory = build_inventory(self.team)
        assert set(inventory.keys()) == {
            "project_context",
            "products_in_use",
            "product_intents",
            "integrations",
            "external_data_sources",
            "signal_source_configs",
            "existing_inbox_reports",
            "recent_dashboards",
            "popular_insights",
            "top_events",
        }


class TestComputeProjectProfile(BaseTest):
    def test_persists_a_new_row_with_inventory_payload(self) -> None:
        profile = compute_project_profile(team=self.team)
        assert profile.source_version == INVENTORY_SOURCE_VERSION
        assert "inventory" in profile.payload
        # Row exists in the DB and points back to this team.
        row = SignalProjectProfile.objects.get(id=profile.profile_id)
        assert row.team_id == self.team.id

    def test_expires_at_is_ttl_after_computed_at(self) -> None:
        profile = compute_project_profile(team=self.team)
        row = SignalProjectProfile.objects.get(id=profile.profile_id)
        delta = row.expires_at - row.computed_at
        # Allow small slack for the two `timezone.now()` calls in the build path.
        assert PROFILE_TTL - timedelta(seconds=2) < delta < PROFILE_TTL + timedelta(seconds=2)


class TestGetProjectProfile(BaseTest):
    def test_returns_existing_fresh_profile_without_recomputing(self) -> None:
        first = compute_project_profile(team=self.team)
        # Second call hits the cache — we should get the same row id back.
        second = get_project_profile(team_id=self.team.id)
        assert second.profile_id == first.profile_id
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 1

    def test_recomputes_when_cached_row_is_expired(self) -> None:
        stale = compute_project_profile(team=self.team)
        # Backdate the row's expires_at to force a cache miss.
        SignalProjectProfile.objects.filter(id=stale.profile_id).update(
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        fresh = get_project_profile(team_id=self.team.id)
        assert fresh.profile_id != stale.profile_id
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 2

    def test_recomputes_when_source_version_does_not_match(self) -> None:
        old = compute_project_profile(team=self.team)
        # Simulate a schema bump by retagging the row to a stale version.
        SignalProjectProfile.objects.filter(id=old.profile_id).update(source_version="v0_legacy")
        fresh = get_project_profile(team_id=self.team.id)
        assert fresh.profile_id != old.profile_id
        assert fresh.source_version == INVENTORY_SOURCE_VERSION

    def test_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        compute_project_profile(team=other)
        # Calling for self.team shouldn't return the other team's profile — it should
        # build a fresh one for self.team.
        result = get_project_profile(team_id=self.team.id)
        row = SignalProjectProfile.objects.get(id=result.profile_id)
        assert row.team_id == self.team.id
