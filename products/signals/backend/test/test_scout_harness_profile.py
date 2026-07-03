"""Tests for the project profile tools and inventory aggregator.

Layered top-down: builder source-readers → `compute_project_profile` end-to-end →
`get_project_profile` cache-hit / cache-miss paths.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.integration import Integration
from posthog.models.product_intent.product_intent import ProductIntent
from posthog.models.user import User

from products.actions.backend.models.action import Action
from products.alerts.backend.models.alert import AlertConfiguration
from products.business_knowledge.backend.models.knowledge_chunk import KnowledgeChunk
from products.business_knowledge.backend.models.knowledge_document import KnowledgeDocument
from products.business_knowledge.backend.models.knowledge_source import KnowledgeSource
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cohorts.backend.models.cohort import Cohort
from products.dashboards.backend.models.dashboard import Dashboard
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.models.insight import Insight
from products.signals.backend.models import SignalProjectProfile, SignalReport, SignalSourceConfig
from products.signals.backend.scout_harness.profile import INVENTORY_SOURCE_VERSION, Inventory, build_inventory
from products.signals.backend.scout_harness.profile.builders import (
    RECENT_ACTIVITY_WINDOW_DAYS,
    REVIEWER_CORRECTIONS_WINDOW_DAYS,
    _business_knowledge,
    _emit_eligibility,
    _existing_inbox_reports,
    _external_data_sources,
    _integrations,
    _product_intents,
    _products_in_use,
    _project_context,
    _recent_actions,
    _recent_activity,
    _recent_alerts,
    _recent_cohorts,
    _recent_dashboards,
    _recent_experiments,
    _recent_feature_flags,
    _recent_hog_flows,
    _recent_hog_functions,
    _recent_notebooks,
    _recent_reviewer_corrections,
    _recent_surveys,
    _signal_source_configs,
)
from products.signals.backend.scout_harness.tools.profile import (
    PROFILE_TTL,
    compute_project_profile,
    get_project_profile,
)
from products.surveys.backend.models import Survey
from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


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
        self.team.app_urls = ["https://app.example.com", "", None]
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
        self.team.has_completed_onboarding_for = ["product_analytics"]
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


class TestEmitEligibility(BaseTest):
    def test_can_emit_when_ai_approved_and_source_on(self) -> None:
        # Default org has AI processing approved; scout source is fail-open (no disabled row).
        result = _emit_eligibility(self.team)
        assert result["ai_processing_approved"] is True
        assert result["source_enabled"] is True
        assert result["can_emit"] is True
        assert result["remediation"] is None

    def test_blocked_with_remediation_when_ai_not_approved(self) -> None:
        # Mutate through team.organization — the exact instance the builder reads — so the change is
        # visible regardless of Django's per-instance FK caching.
        self.team.organization.is_ai_data_processing_approved = False
        self.team.organization.save()
        result = _emit_eligibility(self.team)
        assert result["ai_processing_approved"] is False
        assert result["can_emit"] is False
        # The remediation must be actionable, not a bare reason code — this is the reported symptom.
        assert result["remediation"] and "AI data processing" in result["remediation"]

    def test_blocked_with_remediation_when_source_disabled(self) -> None:
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product=SignalSourceConfig.SourceProduct.SIGNALS_SCOUT,
            source_type=SignalSourceConfig.SourceType.CROSS_SOURCE_ISSUE,
            enabled=False,
        )
        result = _emit_eligibility(self.team)
        assert result["source_enabled"] is False
        assert result["can_emit"] is False
        assert result["remediation"] and "source" in result["remediation"]


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


class TestRecentSurveys(BaseTest):
    def test_caps_at_recent_entity_limit_and_orders_by_updated_at(self) -> None:
        for i in range(7):
            Survey.objects.create(team=self.team, name=f"s{i}", type=Survey.SurveyType.POPOVER)
        result = _recent_surveys(self.team)
        assert result["total_count"] == 7
        assert len(result["recent"]) == 5  # RECENT_ENTITY_LIMIT

    def test_active_count_excludes_drafts_stopped_and_archived(self) -> None:
        # Only `running` should count as active. Draft = no start_date; stopped = end_date in past;
        # scheduled = start_date in the future.
        now = timezone.now()
        Survey.objects.create(team=self.team, name="running", type="popover", start_date=now - timedelta(days=1))
        Survey.objects.create(
            team=self.team,
            name="stopped",
            type="popover",
            start_date=now - timedelta(days=2),
            end_date=now - timedelta(hours=1),
        )
        Survey.objects.create(team=self.team, name="draft", type="popover")
        Survey.objects.create(team=self.team, name="archived", type="popover", start_date=now, archived=True)
        Survey.objects.create(team=self.team, name="scheduled", type="popover", start_date=now + timedelta(days=1))
        result = _recent_surveys(self.team)
        assert result["total_count"] == 5
        assert result["active_count"] == 1

    def test_status_field_derivation(self) -> None:
        now = timezone.now()
        Survey.objects.create(team=self.team, name="r", type="popover", start_date=now - timedelta(days=1))
        Survey.objects.create(team=self.team, name="d", type="popover")
        Survey.objects.create(
            team=self.team,
            name="s",
            type="popover",
            start_date=now - timedelta(days=2),
            end_date=now - timedelta(hours=1),
        )
        Survey.objects.create(team=self.team, name="a", type="popover", archived=True)
        result = _recent_surveys(self.team)
        statuses = {row["name"]: row["status"] for row in result["recent"]}
        assert statuses == {"r": "running", "d": "draft", "s": "stopped", "a": "archived"}

    def test_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        Survey.objects.create(team=other, name="x", type="popover")
        result = _recent_surveys(self.team)
        assert result == {"total_count": 0, "active_count": 0, "recent": []}


class TestRecentFeatureFlags(BaseTest):
    def test_total_active_counts_and_recent_ordering(self) -> None:
        FeatureFlag.objects.create(team=self.team, key="a", name="A", active=True, created_by=self.user)
        FeatureFlag.objects.create(team=self.team, key="b", name="B", active=False, created_by=self.user)
        FeatureFlag.objects.create(team=self.team, key="c", name="C", active=True, deleted=True, created_by=self.user)
        result = _recent_feature_flags(self.team)
        # `c` is soft-deleted — excluded from total.
        assert result["total_count"] == 2
        assert result["active_count"] == 1
        keys = {row["key"] for row in result["recent"]}
        assert keys == {"a", "b"}

    def test_falls_back_to_key_when_name_blank(self) -> None:
        FeatureFlag.objects.create(team=self.team, key="my-flag", name="", active=True, created_by=self.user)
        result = _recent_feature_flags(self.team)
        assert result["recent"][0]["name"] == "my-flag"

    def test_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        FeatureFlag.objects.create(team=other, key="x", name="X", active=True, created_by=self.user)
        result = _recent_feature_flags(self.team)
        assert result["total_count"] == 0


class TestRecentExperiments(BaseTest):
    def _flag(self, key: str) -> FeatureFlag:
        return FeatureFlag.objects.create(team=self.team, key=key, name=key, active=True, created_by=self.user)

    def test_running_count_only_counts_started_unfinished_unarchived(self) -> None:
        now = timezone.now()
        Experiment.objects.create(
            team=self.team, name="running", feature_flag=self._flag("ff-r"), start_date=now - timedelta(days=1)
        )
        Experiment.objects.create(team=self.team, name="draft", feature_flag=self._flag("ff-d"))
        Experiment.objects.create(
            team=self.team,
            name="stopped",
            feature_flag=self._flag("ff-s"),
            start_date=now - timedelta(days=10),
            end_date=now - timedelta(days=1),
        )
        Experiment.objects.create(
            team=self.team, name="archived", feature_flag=self._flag("ff-a"), start_date=now, archived=True
        )
        result = _recent_experiments(self.team)
        assert result["total_count"] == 4
        assert result["running_count"] == 1
        statuses = {row["name"]: row["status"] for row in result["recent"]}
        assert statuses == {
            "running": "running",
            "draft": "draft",
            "stopped": "stopped",
            "archived": "archived",
        }

    def test_carries_feature_flag_key_for_cross_reference(self) -> None:
        Experiment.objects.create(team=self.team, name="exp", feature_flag=self._flag("my-exp-flag"))
        result = _recent_experiments(self.team)
        assert result["recent"][0]["feature_flag_key"] == "my-exp-flag"

    def test_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        Experiment.objects.create(
            team=other, name="x", feature_flag=FeatureFlag.objects.create(team=other, key="o", created_by=self.user)
        )
        result = _recent_experiments(self.team)
        assert result["total_count"] == 0


class TestRecentAlerts(BaseTest):
    def _insight(self, name: str = "i") -> Insight:
        return Insight.objects.create(team=self.team, name=name)

    def test_total_and_enabled_counts(self) -> None:
        AlertConfiguration.objects.create(team=self.team, insight=self._insight("a"), name="on", enabled=True)
        AlertConfiguration.objects.create(team=self.team, insight=self._insight("b"), name="off", enabled=False)
        result = _recent_alerts(self.team)
        assert result["total_count"] == 2
        assert result["enabled_count"] == 1

    def test_orders_by_created_at_desc(self) -> None:
        # AlertConfiguration has no `updated_at` (CreatedMetaFields only) — sort uses
        # created_at, which captures the high-signal "alert was newly configured" moment.
        first = AlertConfiguration.objects.create(team=self.team, insight=self._insight("a"), name="first")
        AlertConfiguration.objects.filter(id=first.id).update(created_at=timezone.now() - timedelta(days=2))
        AlertConfiguration.objects.create(team=self.team, insight=self._insight("b"), name="second")
        result = _recent_alerts(self.team)
        assert [r["name"] for r in result["recent"]] == ["second", "first"]

    def test_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        AlertConfiguration.objects.create(team=other, insight=Insight.objects.create(team=other, name="i"), name="x")
        result = _recent_alerts(self.team)
        assert result["total_count"] == 0


class TestRecentHogFunctions(BaseTest):
    def test_total_enabled_counts_and_excludes_deleted(self) -> None:
        HogFunction.objects.create(team=self.team, name="a", enabled=True, type="destination", hog="")
        HogFunction.objects.create(team=self.team, name="b", enabled=False, type="transformation", hog="")
        HogFunction.objects.create(team=self.team, name="c", enabled=True, type="destination", deleted=True, hog="")
        result = _recent_hog_functions(self.team)
        assert result["total_count"] == 2
        assert result["enabled_count"] == 1

    def test_carries_type_and_kind_for_orientation(self) -> None:
        HogFunction.objects.create(
            team=self.team, name="dest", enabled=True, type="destination", kind="webhook", hog=""
        )
        result = _recent_hog_functions(self.team)
        row = result["recent"][0]
        assert row["type"] == "destination"
        assert row["kind"] == "webhook"

    def test_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        HogFunction.objects.create(team=other, name="x", enabled=True, type="destination", hog="")
        result = _recent_hog_functions(self.team)
        assert result["total_count"] == 0


class TestRecentHogFlows(BaseTest):
    def test_total_active_counts_excludes_archived(self) -> None:
        HogFlow.objects.create(team=self.team, name="draft", status="draft")
        HogFlow.objects.create(team=self.team, name="active", status="active")
        HogFlow.objects.create(team=self.team, name="archived", status="archived")
        result = _recent_hog_flows(self.team)
        assert result["total_count"] == 3
        assert result["active_count"] == 2  # everything except archived

    def test_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        HogFlow.objects.create(team=other, name="x", status="active")
        result = _recent_hog_flows(self.team)
        assert result["total_count"] == 0


class TestRecentNotebooks(BaseTest):
    def test_orders_by_last_modified_at_desc_and_caps_at_limit(self) -> None:
        for i in range(7):
            Notebook.objects.create(team=self.team, title=f"n{i}")
        result = _recent_notebooks(self.team)
        assert result["total_count"] == 7
        assert len(result["recent"]) == 5

    def test_excludes_deleted(self) -> None:
        Notebook.objects.create(team=self.team, title="live")
        Notebook.objects.create(team=self.team, title="gone", deleted=True)
        result = _recent_notebooks(self.team)
        assert result["total_count"] == 1
        assert result["recent"][0]["title"] == "live"

    def test_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        Notebook.objects.create(team=other, title="x")
        result = _recent_notebooks(self.team)
        assert result == {"total_count": 0, "recent": []}


class TestRecentCohorts(BaseTest):
    def test_orders_by_created_at_desc(self) -> None:
        old = Cohort.objects.create(team=self.team, name="old", created_by=self.user)
        Cohort.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(days=3))
        Cohort.objects.create(team=self.team, name="new", created_by=self.user)
        result = _recent_cohorts(self.team)
        assert [r["name"] for r in result["recent"]] == ["new", "old"]

    def test_carries_is_static_and_count(self) -> None:
        Cohort.objects.create(team=self.team, name="static", is_static=True, count=42, created_by=self.user)
        result = _recent_cohorts(self.team)
        row = result["recent"][0]
        assert row["is_static"] is True
        assert row["count"] == 42

    def test_excludes_deleted_and_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        Cohort.objects.create(team=self.team, name="kept", created_by=self.user)
        Cohort.objects.create(team=self.team, name="gone", deleted=True, created_by=self.user)
        Cohort.objects.create(team=other, name="other-team", created_by=self.user)
        result = _recent_cohorts(self.team)
        assert result["total_count"] == 1
        assert result["recent"][0]["name"] == "kept"


class TestRecentActions(BaseTest):
    def test_orders_by_updated_at_desc(self) -> None:
        a = Action.objects.create(team=self.team, name="a", created_by=self.user)
        Action.objects.filter(id=a.id).update(updated_at=timezone.now() - timedelta(days=1))
        Action.objects.create(team=self.team, name="b", created_by=self.user)
        result = _recent_actions(self.team)
        assert [r["name"] for r in result["recent"]] == ["b", "a"]

    def test_excludes_deleted(self) -> None:
        Action.objects.create(team=self.team, name="kept", created_by=self.user)
        Action.objects.create(team=self.team, name="gone", deleted=True, created_by=self.user)
        result = _recent_actions(self.team)
        assert result["total_count"] == 1
        assert result["recent"][0]["name"] == "kept"

    def test_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        Action.objects.create(team=other, name="x", created_by=self.user)
        result = _recent_actions(self.team)
        assert result["total_count"] == 0


class TestRecentActivity(BaseTest):
    def _log(
        self,
        *,
        scope: str,
        team=None,
        user=None,
        created_at=None,
        was_impersonated: bool | None = False,
        is_system: bool | None = False,
        activity: str = "updated",
    ) -> ActivityLog:
        # Direct create with `created_at=...` works because the model uses
        # `default=timezone.now` rather than `auto_now_add` — lets us backdate rows
        # to test the windowing without a follow-up `.update()` dance.
        return ActivityLog.objects.create(
            team_id=(team or self.team).id,
            user=user,
            activity=activity,
            scope=scope,
            item_id="x",
            was_impersonated=was_impersonated,
            is_system=is_system,
            created_at=created_at or timezone.now(),
        )

    def test_groups_scopes_by_edit_count_descending(self) -> None:
        self._log(scope="FeatureFlag")
        self._log(scope="FeatureFlag")
        self._log(scope="FeatureFlag")
        self._log(scope="Survey")
        result = _recent_activity(self.team)
        assert result["window_days"] == RECENT_ACTIVITY_WINDOW_DAYS
        assert [row["scope"] for row in result["by_scope"]] == ["FeatureFlag", "Survey"]
        assert [row["edits"] for row in result["by_scope"]] == [3, 1]

    def test_distinct_user_count_and_last_edit_per_scope(self) -> None:
        u1 = self._make_user("u1@example.com")
        u2 = self._make_user("u2@example.com")
        # Two users, three edits — `users` should be 2, not 3.
        first = self._log(scope="Experiment", user=u1)
        ActivityLog.objects.filter(id=first.id).update(created_at=timezone.now() - timedelta(days=2))
        self._log(scope="Experiment", user=u2)
        last = self._log(scope="Experiment", user=u2)
        result = _recent_activity(self.team)
        row = next(r for r in result["by_scope"] if r["scope"] == "Experiment")
        assert row["edits"] == 3
        assert row["users"] == 2
        # `last_edit` reflects the most recent row in the window.
        assert row["last_edit"] is not None
        assert row["last_edit"] == last.created_at.isoformat()

    def test_excludes_impersonated_and_system_rows(self) -> None:
        # The partial index treats both flags as required-False; we mirror that.
        self._log(scope="Survey")  # counted
        self._log(scope="Survey", was_impersonated=True)
        self._log(scope="Survey", is_system=True)
        self._log(scope="Survey", was_impersonated=None)
        self._log(scope="Survey", is_system=None)
        result = _recent_activity(self.team)
        survey = next(r for r in result["by_scope"] if r["scope"] == "Survey")
        assert survey["edits"] == 1

    def test_excludes_rows_outside_window(self) -> None:
        old = self._log(scope="Cohort")
        ActivityLog.objects.filter(id=old.id).update(
            created_at=timezone.now() - timedelta(days=RECENT_ACTIVITY_WINDOW_DAYS + 1),
        )
        recent = self._log(scope="Cohort")
        result = _recent_activity(self.team)
        cohort = next(r for r in result["by_scope"] if r["scope"] == "Cohort")
        assert cohort["edits"] == 1
        assert cohort["last_edit"] == recent.created_at.isoformat()

    def test_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        self._log(scope="FeatureFlag", team=other)
        result = _recent_activity(self.team)
        assert result == {"window_days": RECENT_ACTIVITY_WINDOW_DAYS, "by_scope": []}

    def test_empty_when_no_activity(self) -> None:
        # A quiet team should return the section with no rows — distinguishable from
        # an exception (which would propagate; profile build has no defensive wrapping
        # at this layer for indexed Postgres readers).
        result = _recent_activity(self.team)
        assert result == {"window_days": RECENT_ACTIVITY_WINDOW_DAYS, "by_scope": []}

    def _make_user(self, email: str) -> User:
        return User.objects.create(email=email, distinct_id=email)


class TestRecentReviewerCorrections(BaseTest):
    def _log_correction(self, *, team=None, created_at=None, detail=None, activity="suggested_reviewers_changed"):
        return ActivityLog.objects.create(
            team_id=(team or self.team).id,
            activity=activity,
            scope="SignalReport",
            item_id=str(uuid4()),
            was_impersonated=False,
            is_system=False,
            created_at=created_at or timezone.now(),
            detail=detail
            if detail is not None
            else {
                "name": "Report title",
                "changes": [
                    {
                        "type": "SignalReport",
                        "action": "changed",
                        "field": "suggested_reviewers",
                        "before": ["alice"],
                        "after": ["bob"],
                    }
                ],
            },
        )

    def test_parses_corrections_and_excludes_noise(self) -> None:
        correction = self._log_correction()
        # None of these are reviewer corrections: other activity on the same scope,
        # another team's correction, and a correction outside the window.
        self._log_correction(activity="updated")
        other = self.organization.teams.create(name="other")
        self._log_correction(team=other)
        self._log_correction(created_at=timezone.now() - timedelta(days=REVIEWER_CORRECTIONS_WINDOW_DAYS + 1))

        result = _recent_reviewer_corrections(self.team)
        assert result["window_days"] == REVIEWER_CORRECTIONS_WINDOW_DAYS
        (row,) = result["corrections"]
        assert row == {
            "report_id": str(correction.item_id),
            "report_title": "Report title",
            "before": ["alice"],
            "after": ["bob"],
            "at": correction.created_at.isoformat(),
        }

    def test_malformed_detail_degrades_to_empty_lists(self) -> None:
        self._log_correction(detail={})
        result = _recent_reviewer_corrections(self.team)
        (row,) = result["corrections"]
        assert row["before"] == []
        assert row["after"] == []
        assert row["report_title"] is None


class TestBusinessKnowledge(BaseTest):
    def test_returns_zeroed_section_when_no_sources(self) -> None:
        result = _business_knowledge(self.team)
        assert result == {
            "total_count": 0,
            "ready_count": 0,
            "document_count": 0,
            "chunk_count": 0,
            "recent": [],
        }

    def test_counts_ready_sources_and_aggregates_docs_and_chunks(self) -> None:
        ready = KnowledgeSource.objects.create(team=self.team, name="Docs", source_type="text", status="ready")
        processing = KnowledgeSource.objects.create(team=self.team, name="URLs", source_type="url", status="processing")
        # doc1 carries 2 chunks — guards against join inflation in the shared aggregate.
        doc1 = KnowledgeDocument.objects.create(team=self.team, source=ready, stable_id="d1")
        doc2 = KnowledgeDocument.objects.create(team=self.team, source=ready, stable_id="d2")
        KnowledgeDocument.objects.create(team=self.team, source=processing, stable_id="d3")
        # Tombstoned doc (and its chunk) must not count toward searchable volume.
        tombstoned = KnowledgeDocument.objects.create(
            team=self.team, source=ready, stable_id="d4", tombstoned_at=timezone.now()
        )
        for i in range(2):
            KnowledgeChunk.objects.create(
                id=uuid4(), team=self.team, source=ready, document=doc1, ordinal=i, content="c", char_count=1
            )
        KnowledgeChunk.objects.create(
            id=uuid4(), team=self.team, source=ready, document=doc2, ordinal=0, content="c", char_count=1
        )
        KnowledgeChunk.objects.create(
            id=uuid4(), team=self.team, source=ready, document=tombstoned, ordinal=0, content="c", char_count=1
        )

        result = _business_knowledge(self.team)
        assert result["total_count"] == 2
        assert result["ready_count"] == 1
        assert result["document_count"] == 3
        assert result["chunk_count"] == 3
        assert len(result["recent"]) == 2
        assert result["recent"][0]["name"] in ("Docs", "URLs")

    def test_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        KnowledgeSource.objects.create(team=other, name="Other", source_type="text", status="ready")
        result = _business_knowledge(self.team)
        assert result["total_count"] == 0


class TestBuildInventory(BaseTest):
    def test_returns_a_validated_inventory_with_all_sections(self) -> None:
        inventory = build_inventory(self.team)
        assert isinstance(inventory, Inventory)
        assert set(inventory.model_dump().keys()) == {
            "project_context",
            "products_in_use",
            "product_intents",
            "integrations",
            "external_data_sources",
            "signal_source_configs",
            "emit_eligibility",
            "existing_inbox_reports",
            "recent_activity",
            "recent_reviewer_corrections",
            "recent_dashboards",
            "recent_surveys",
            "recent_feature_flags",
            "recent_experiments",
            "recent_alerts",
            "recent_hog_functions",
            "recent_hog_flows",
            "recent_notebooks",
            "recent_cohorts",
            "recent_actions",
            "business_knowledge",
            "top_events",
        }

    def test_persisted_payload_revalidates_against_the_schema(self) -> None:
        # The stored jsonb is the dumped model; round-tripping it back through `Inventory`
        # is the contract the scout skills rely on, so guard that the dump stays valid.
        profile = compute_project_profile(team=self.team)
        Inventory.model_validate(profile.payload["inventory"])


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
        assert second is not None and second.profile_id == first.profile_id
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 1

    def test_recomputes_when_cached_row_is_expired(self) -> None:
        stale = compute_project_profile(team=self.team)
        # Backdate the row's expires_at to force a cache miss.
        SignalProjectProfile.objects.filter(id=stale.profile_id).update(
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        fresh = get_project_profile(team_id=self.team.id)
        assert fresh is not None and fresh.profile_id != stale.profile_id
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 2

    def test_recomputes_when_source_version_does_not_match(self) -> None:
        old = compute_project_profile(team=self.team)
        # Simulate a schema bump by retagging the row to a stale version.
        SignalProjectProfile.objects.filter(id=old.profile_id).update(source_version="v0_legacy")
        fresh = get_project_profile(team_id=self.team.id)
        assert fresh is not None and fresh.profile_id != old.profile_id
        assert fresh.source_version == INVENTORY_SOURCE_VERSION

    def test_team_isolated(self) -> None:
        other = self.organization.teams.create(name="other")
        compute_project_profile(team=other)
        # Calling for self.team shouldn't return the other team's profile — it should
        # build a fresh one for self.team.
        result = get_project_profile(team_id=self.team.id)
        assert result is not None
        row = SignalProjectProfile.objects.get(id=result.profile_id)
        assert row.team_id == self.team.id

    def test_force_refresh_rebuilds_even_when_cache_is_fresh(self) -> None:
        cached = compute_project_profile(team=self.team)
        # Default fetch hits the cache — same row.
        sanity = get_project_profile(team_id=self.team.id)
        assert sanity is not None and sanity.profile_id == cached.profile_id
        # `force_refresh=True` skips the cache and the post-lock re-check, persisting a
        # second row even though the first is still well within TTL.
        fresh = get_project_profile(team_id=self.team.id, force_refresh=True)
        assert fresh is not None and fresh.profile_id != cached.profile_id
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 2

    def test_lazy_build_false_returns_none_on_cache_miss_without_building(self) -> None:
        # Read-only callers (untrusted, CSRF-reachable GETs) pass `lazy_build=False` so a
        # miss returns None instead of running the inventory build + persisting a row.
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 0
        result = get_project_profile(team_id=self.team.id, lazy_build=False)
        assert result is None
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 0

    def test_lazy_build_false_returns_cached_row_when_fresh(self) -> None:
        cached = compute_project_profile(team=self.team)
        result = get_project_profile(team_id=self.team.id, lazy_build=False)
        assert result is not None and result.profile_id == cached.profile_id
        # No new row — the read-only path served the cache.
        assert SignalProjectProfile.objects.filter(team=self.team).count() == 1
