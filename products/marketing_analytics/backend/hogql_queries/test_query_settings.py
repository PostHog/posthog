import sys

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    BaseMathType,
    ConversionGoalFilter1,
    DateRange,
    MarketingAnalyticsAttributionBreakdown,
    MarketingAnalyticsAttributionPathsQuery,
    MarketingAnalyticsAttributionQuery,
    MarketingAnalyticsTableQuery,
)

from posthog.hogql.constants import MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY

from products.marketing_analytics.backend.hogql_queries.attribution_paths_query_runner import (
    MarketingAnalyticsAttributionPathsQueryRunner,
)
from products.marketing_analytics.backend.hogql_queries.attribution_table_query_runner import (
    MarketingAnalyticsAttributionQueryRunner,
)
from products.marketing_analytics.backend.hogql_queries.constants import MARKETING_SPILL_AFTER_BYTES
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner import (
    MarketingAnalyticsTableQueryRunner,
)

GOAL_ID = "goal-1"


class _Stop(Exception):
    pass


class TestMarketingQuerySettings(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        config = self.team.marketing_analytics_config
        config.conversion_goals = [
            ConversionGoalFilter1(
                kind="EventsNode",
                event="purchase",
                name="Purchases",
                conversion_goal_id=GOAL_ID,
                conversion_goal_name="Purchases",
                schema_map={},
                math=BaseMathType.TOTAL,
            ).model_dump()
        ]
        config.save()

    # A spill threshold above the per-query memory limit can never fire: the query hits the limit
    # first. The shared 22 GiB constant is sized for funnels, whose peak is an order of magnitude
    # above these queries, and using it here shipped a setting that did nothing.
    def test_spill_threshold_is_reachable(self):
        peak_bytes = 2 * 1024 * 1024 * 1024
        self.assertLess(MARKETING_SPILL_AFTER_BYTES, peak_bytes)
        self.assertLess(MARKETING_SPILL_AFTER_BYTES, MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY)

    @parameterized.expand(
        [
            ("attribution_table", MarketingAnalyticsAttributionQueryRunner),
            ("attribution_paths", MarketingAnalyticsAttributionPathsQueryRunner),
            ("marketing_table", MarketingAnalyticsTableQueryRunner),
        ]
    )
    def test_the_runner_passes_the_spill_threshold(self, name, runner_class):
        # The settings travel beside the SQL rather than inside it, so a snapshot of the printed
        # query cannot show whether they were passed at all.
        date_range = DateRange(date_from="2023-01-01", date_to="2023-01-31")
        query: (
            MarketingAnalyticsTableQuery | MarketingAnalyticsAttributionPathsQuery | MarketingAnalyticsAttributionQuery
        )
        if runner_class is MarketingAnalyticsTableQueryRunner:
            query = MarketingAnalyticsTableQuery(dateRange=date_range, properties=[], select=[])
        elif runner_class is MarketingAnalyticsAttributionPathsQueryRunner:
            query = MarketingAnalyticsAttributionPathsQuery(
                conversionGoalId=GOAL_ID, dateRange=date_range, properties=[]
            )
        else:
            query = MarketingAnalyticsAttributionQuery(
                conversionGoalId=GOAL_ID,
                breakdownBy=MarketingAnalyticsAttributionBreakdown.CHANNEL,
                dateRange=date_range,
                properties=[],
            )

        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            raise _Stop

        runner = runner_class(query=query, team=self.team)
        with patch.object(sys.modules[runner_class.__module__], "execute_hogql_query", _capture):
            with self.assertRaises(_Stop):
                runner.calculate()

        settings = captured.get("settings")
        assert settings is not None, f"{name} passed no settings to ClickHouse"
        self.assertEqual(settings.max_bytes_before_external_group_by, MARKETING_SPILL_AFTER_BYTES)
