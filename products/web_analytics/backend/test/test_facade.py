from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models import Team

from products.web_analytics.backend.facade import (
    api as facade_api,
    hogql as facade_hogql,
    queries as facade_queries,
    temporal as facade_temporal,
)
from products.web_analytics.backend.facade.contracts import FilterPreset, UserRef
from products.web_analytics.backend.models import WebAnalyticsFilterPreset


class TestWebAnalyticsFacadeReExports(APIBaseTest):
    @parameterized.expand(
        [
            ("web_overview", "WebOverviewQueryRunner"),
            ("stats_table", "WebStatsTableQueryRunner"),
            ("web_goals", "WebGoalsQueryRunner"),
            ("notable_changes", "WebNotableChangesQueryRunner"),
            ("external_clicks", "WebExternalClicksTableQueryRunner"),
            ("web_vitals_path_breakdown", "WebVitalsPathBreakdownQueryRunner"),
            ("page_url_search_query_runner", "PageUrlSearchQueryRunner"),
            ("session_attribution_explorer_query_runner", "SessionAttributionExplorerQueryRunner"),
        ]
    )
    def test_queries_reexports_are_the_runner_classes(self, module_name: str, class_name: str) -> None:
        from importlib import import_module

        internal = getattr(import_module(f"products.web_analytics.backend.hogql_queries.{module_name}"), class_name)
        self.assertIs(getattr(facade_queries, class_name), internal)

    def test_queries_reexports_runner_modules_for_monkeypatching(self) -> None:
        from products.web_analytics.backend.hogql_queries import stats_table, web_overview

        self.assertIs(facade_queries.web_overview, web_overview)
        self.assertIs(facade_queries.stats_table, stats_table)

    def test_hogql_reexports_shared_tables(self) -> None:
        from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS

        self.assertIs(facade_hogql.BOT_DEFINITIONS, BOT_DEFINITIONS)

    def test_temporal_reexports_wiring(self) -> None:
        from products.web_analytics.backend.temporal import ACTIVITIES, WORKFLOWS

        self.assertEqual(facade_temporal.WORKFLOWS, WORKFLOWS)
        self.assertEqual(facade_temporal.ACTIVITIES, ACTIVITIES)


class TestWebAnalyticsFacadeFilterPresets(APIBaseTest):
    def _create_preset(self, name: str = "Preset", deleted: bool = False) -> WebAnalyticsFilterPreset:
        return WebAnalyticsFilterPreset.objects.create(
            team=self.team,
            name=name,
            description="d",
            filters={"a": 1},
            created_by=self.user,
            last_modified_by=self.user,
            deleted=deleted,
        )

    def test_list_returns_contracts_not_models(self) -> None:
        preset = self._create_preset()

        result = facade_api.list_filter_presets(self.team.id)

        self.assertEqual(len(result), 1)
        contract = result[0]
        self.assertIsInstance(contract, FilterPreset)
        self.assertEqual(contract.id, preset.id)
        self.assertEqual(contract.name, "Preset")
        self.assertEqual(contract.filters, {"a": 1})
        self.assertEqual(
            contract.created_by, UserRef(self.user.id, self.user.email, self.user.first_name, self.user.last_name)
        )

    def test_list_excludes_deleted_by_default(self) -> None:
        self._create_preset(name="live")
        self._create_preset(name="gone", deleted=True)

        self.assertEqual([p.name for p in facade_api.list_filter_presets(self.team.id)], ["live"])
        names = {p.name for p in facade_api.list_filter_presets(self.team.id, include_deleted=True)}
        self.assertEqual(names, {"live", "gone"})

    def test_list_scopes_to_team(self) -> None:
        self._create_preset()
        other = Team.objects.create(organization=self.organization, name="other")
        self.assertEqual(facade_api.list_filter_presets(other.id), [])

    def test_get_returns_contract_or_none(self) -> None:
        preset = self._create_preset()

        self.assertEqual(facade_api.get_filter_preset(self.team.id, preset.short_id).id, preset.id)
        self.assertIsNone(facade_api.get_filter_preset(self.team.id, "nope"))
