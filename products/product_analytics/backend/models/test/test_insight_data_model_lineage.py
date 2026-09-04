from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import SimpleTestCase

from posthog.models.team import Team

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.product_analytics.backend.facade.api import insight_data_model_dependencies_by_saved_query_ids
from products.product_analytics.backend.lineage.extraction import extract_saved_query_names, query_fingerprint
from products.product_analytics.backend.lineage.synchronization import synchronize_insight_data_model_dependencies
from products.product_analytics.backend.models.insight import Insight
from products.product_analytics.backend.models.insight_data_model_dependency import InsightDataModelDependency


class TestInsightDataModelDependencyExtraction(SimpleTestCase):
    def test_extracts_recursive_structured_and_hogql_references(self) -> None:
        query = {
            "kind": "InsightVizNode",
            "source": {
                "series": [
                    {"kind": "DataWarehouseNode", "table_name": "orders"},
                    {"kind": "FunnelsDataWarehouseNode", "table_name": "customers"},
                    {"kind": "LifecycleDataWarehouseNode", "table_name": "orders"},
                    {"type": "data_warehouse", "table_name": "subscriptions"},
                ],
                "nested": {"kind": "HogQLQuery", "query": "SELECT * FROM customers JOIN products USING (id)"},
                "direct": {
                    "kind": "HogQLQuery",
                    "query": "SELECT * FROM ignored_direct_table",
                    "connectionId": "connection-id",
                },
                "response": {"kind": "DataWarehouseNode", "table_name": "ignored_response"},
                "results": [{"kind": "DataWarehouseNode", "table_name": "ignored_results"}],
            },
        }

        assert extract_saved_query_names(query) == {"orders", "customers", "products", "subscriptions"}

    def test_invalid_discovered_hogql_fails_extraction(self) -> None:
        with self.assertRaises(Exception):
            extract_saved_query_names({"kind": "HogQLQuery", "query": "SELECT * FROM"})

    def test_fingerprint_is_independent_of_object_key_order(self) -> None:
        assert query_fingerprint({"kind": "HogQLQuery", "query": "SELECT 1"}) == query_fingerprint(
            {"query": "SELECT 1", "kind": "HogQLQuery"}
        )


class TestInsightDataModelDependencySynchronization(BaseTest):
    def _saved_query(
        self, name: str, *, team: Team | None = None, is_materialized: bool = False
    ) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=team or self.team,
            name=name,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            is_materialized=is_materialized,
        )

    def _synchronize(self, insight: Insight, query: dict) -> None:
        result = synchronize_insight_data_model_dependencies(
            team_id=insight.team_id,
            insight_id=insight.id,
            query_snapshot=query,
            fingerprint=query_fingerprint(query),
            insight_model=Insight,
        )
        assert result.status == "synchronized"

    def _dependency_ids(self, insight: Insight) -> set:
        return set(
            InsightDataModelDependency.objects.for_team(insight.team_id)
            .filter(insight_id=insight.id)
            .values_list("saved_query_id", flat=True)
        )

    def test_saved_query_rename_keeps_the_stable_dependency_id(self) -> None:
        saved_query = self._saved_query("orders")
        query = {"kind": "HogQLQuery", "query": "SELECT * FROM orders"}
        insight = Insight.objects.create(team=self.team, query=query)
        self._synchronize(insight, query)

        saved_query.name = "renamed_orders"
        saved_query.save(update_fields=["name"])

        assert self._dependency_ids(insight) == {saved_query.id}

    def test_replaces_dependencies_and_successful_empty_deletes_them(self) -> None:
        orders = self._saved_query("orders")
        customers = self._saved_query("customers")
        insight = Insight.objects.create(team=self.team, query={"kind": "HogQLQuery", "query": "SELECT 1"})

        replacement_query = {"kind": "HogQLQuery", "query": "SELECT * FROM customers"}
        insight.query = replacement_query
        insight.save(update_fields=["query"])
        InsightDataModelDependency.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            insight_id=insight.id,
            saved_query_id=orders.id,
            query_fingerprint="old",
        )
        self._synchronize(insight, replacement_query)
        assert self._dependency_ids(insight) == {customers.id}

        empty_query = {"kind": "HogQLQuery", "query": "SELECT 1"}
        insight.query = empty_query
        insight.save(update_fields=["query"])
        self._synchronize(insight, empty_query)
        assert self._dependency_ids(insight) == set()

    def test_parse_failure_preserves_existing_dependencies(self) -> None:
        saved_query = self._saved_query("orders")
        valid_query = {"kind": "HogQLQuery", "query": "SELECT * FROM orders"}
        insight = Insight.objects.create(team=self.team, query=valid_query)
        self._synchronize(insight, valid_query)

        invalid_query = {"kind": "HogQLQuery", "query": "SELECT * FROM"}
        insight.query = invalid_query
        Insight.objects.filter(id=insight.id).update(query=invalid_query)
        result = synchronize_insight_data_model_dependencies(
            team_id=self.team.id,
            insight_id=insight.id,
            query_snapshot=invalid_query,
            fingerprint=query_fingerprint(invalid_query),
            insight_model=Insight,
        )

        assert result.status == "failed"
        assert self._dependency_ids(insight) == {saved_query.id}

    def test_stale_save_callback_does_not_overwrite_newer_dependencies(self) -> None:
        old_saved_query = self._saved_query("old_view")
        new_saved_query = self._saved_query("new_view")
        old_query = {"kind": "HogQLQuery", "query": "SELECT * FROM old_view"}
        new_query = {"kind": "HogQLQuery", "query": "SELECT * FROM new_view"}

        with self.captureOnCommitCallbacks(execute=False) as stale_callbacks:
            insight = Insight.objects.create(team=self.team, query=old_query)
        insight.query = new_query
        with self.captureOnCommitCallbacks(execute=True):
            insight.save(update_fields=["query"])

        assert self._dependency_ids(insight) == {new_saved_query.id}
        stale_callbacks[0]()
        assert self._dependency_ids(insight) == {new_saved_query.id}
        assert old_saved_query.id not in self._dependency_ids(insight)

    def test_rolled_back_save_does_not_suppress_the_next_sync(self) -> None:
        old_saved_query = self._saved_query("old_view")
        new_saved_query = self._saved_query("new_view")
        old_query = {"kind": "HogQLQuery", "query": "SELECT * FROM old_view"}
        new_query = {"kind": "HogQLQuery", "query": "SELECT * FROM new_view"}
        insight = Insight.objects.create(team=self.team, query=old_query)
        self._synchronize(insight, old_query)

        insight.query = new_query
        with self.assertRaises(ValueError):
            with transaction.atomic():
                insight.save(update_fields=["query"])
                raise ValueError("roll back")

        with self.captureOnCommitCallbacks(execute=True):
            insight.save(update_fields=["query"])

        assert self._dependency_ids(insight) == {new_saved_query.id}
        assert old_saved_query.id not in self._dependency_ids(insight)

    def test_sync_is_team_scoped_and_includes_materialized_saved_queries(self) -> None:
        materialized = self._saved_query("shared_view", is_materialized=True)
        other_team = Team.objects.create(organization=self.organization)
        self._saved_query("shared_view", team=other_team, is_materialized=True)
        query = {"kind": "DataWarehouseNode", "table_name": "shared_view"}
        insight = Insight.objects.create(team=self.team, query=query)

        self._synchronize(insight, query)

        assert self._dependency_ids(insight) == {materialized.id}

    def test_facade_excludes_dependency_rows_with_a_mismatched_insight_team(self) -> None:
        saved_query = self._saved_query("orders")
        other_team = Team.objects.create(organization=self.organization)
        other_insight = Insight.objects.create(team=other_team, query={"kind": "HogQLQuery", "query": "SELECT 1"})
        InsightDataModelDependency.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            insight_id=other_insight.id,
            saved_query_id=saved_query.id,
            query_fingerprint="fingerprint",
        )

        dependencies = insight_data_model_dependencies_by_saved_query_ids(
            team_id=self.team.id,
            saved_query_ids=[saved_query.id],
        )

        assert dependencies == []

    def test_event_only_insight_does_not_schedule_lineage_work(self) -> None:
        query = {
            "kind": "InsightVizNode",
            "source": {
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "event": "$pageview"}],
            },
        }

        with patch("products.data_modeling.backend.facade.api.saved_query_ids_by_names") as resolve_saved_queries:
            with self.captureOnCommitCallbacks(execute=True):
                Insight.objects.create(team=self.team, query=query)

        resolve_saved_queries.assert_not_called()

    def test_save_ignores_an_in_memory_query_excluded_from_update_fields(self) -> None:
        old_saved_query = self._saved_query("old_view")
        self._saved_query("new_view")
        old_query = {"kind": "HogQLQuery", "query": "SELECT * FROM old_view"}
        with self.captureOnCommitCallbacks(execute=True):
            insight = Insight.objects.create(team=self.team, query=old_query)

        insight.query = {"kind": "HogQLQuery", "query": "SELECT * FROM new_view"}
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            insight.name = "Updated name"
            insight.save(update_fields=["name"])

        assert callbacks == []
        assert self._dependency_ids(insight) == {old_saved_query.id}

    def test_backfill_dry_run_apply_resume_and_repeat_apply(self) -> None:
        saved_query = self._saved_query("orders")
        first_insight = Insight.objects.create(
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT * FROM orders"},
        )
        Insight.objects.create(
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT * FROM orders"},
        )

        call_command("backfill_insight_data_model_dependencies", team_id=self.team.id, stdout=StringIO())
        assert InsightDataModelDependency.objects.for_team(self.team.id).count() == 0

        call_command(
            "backfill_insight_data_model_dependencies",
            apply=True,
            team_id=self.team.id,
            limit=1,
            stdout=StringIO(),
        )
        assert InsightDataModelDependency.objects.for_team(self.team.id).count() == 1

        for _ in range(2):
            call_command(
                "backfill_insight_data_model_dependencies",
                apply=True,
                team_id=self.team.id,
                after_team_id=self.team.id,
                after_insight_id=first_insight.id,
                stdout=StringIO(),
            )

        dependencies = InsightDataModelDependency.objects.for_team(self.team.id)
        assert dependencies.count() == 2
        assert set(dependencies.values_list("saved_query_id", flat=True)) == {saved_query.id}

    def test_backfill_covers_unsaved_insights_that_sit_on_a_dashboard(self) -> None:
        saved_query = self._saved_query("orders")
        query = {"kind": "HogQLQuery", "query": "SELECT * FROM orders"}
        on_dashboard = Insight.objects.create(team=self.team, query=query, saved=False)
        DashboardTile.objects.create(
            insight=on_dashboard,
            dashboard=Dashboard.objects.create(team=self.team, name="the dashboard"),
        )
        loose = Insight.objects.create(team=self.team, query=query, saved=False)

        call_command(
            "backfill_insight_data_model_dependencies",
            apply=True,
            team_id=self.team.id,
            stdout=StringIO(),
        )

        assert self._dependency_ids(on_dashboard) == {saved_query.id}
        assert self._dependency_ids(loose) == set()

    def test_backfill_reports_failure_after_processing_the_batch(self) -> None:
        saved_query = self._saved_query("orders")
        Insight.objects.create(
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT * FROM"},
        )
        valid_insight = Insight.objects.create(
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT * FROM orders"},
        )

        with self.assertRaises(CommandError):
            call_command(
                "backfill_insight_data_model_dependencies",
                apply=True,
                team_id=self.team.id,
                stdout=StringIO(),
            )

        assert self._dependency_ids(valid_insight) == {saved_query.id}
