from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import Mock, patch

from posthog.schema import (
    BaseMathType,
    ConversionGoalFilter1,
    DateRange,
    MarketingAnalyticsTableQuery,
    MarketingAnalyticsTableQueryResponse,
    NodeKind,
)

from posthog.hogql import ast

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.marketing_analytics.backend.hogql_queries.adapters.base import MarketingSourceAdapter
from products.marketing_analytics.backend.hogql_queries.constants import DEFAULT_LIMIT
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner import (
    MarketingAnalyticsTableQueryRunner,
)


class TestMarketingAnalyticsTableQueryRunner(ClickhouseTestMixin, BaseTest):
    """
    Test suite for MarketingAnalyticsTableQueryRunner.

    Covers basic functionality, adapter integration, conversion goals,
    date range handling, pagination, and error handling.
    """

    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.default_date_range = DateRange(date_from="2023-01-01", date_to="2023-01-31")
        self.default_query = MarketingAnalyticsTableQuery(
            dateRange=self.default_date_range,
            limit=DEFAULT_LIMIT,
            offset=0,
            properties=[],
        )

    def _create_query_runner(self, query: MarketingAnalyticsTableQuery = None) -> MarketingAnalyticsTableQueryRunner:
        """Create a query runner with standard configuration"""
        if query is None:
            query = self.default_query
        return MarketingAnalyticsTableQueryRunner(query=query, team=self.team)

    def _create_mock_adapter(self, name: str, validation_result: bool = True) -> Mock:
        """Create a mock adapter for testing"""
        mock_adapter = Mock(spec=MarketingSourceAdapter)
        mock_adapter.name = name
        mock_adapter.validate.return_value = Mock(is_valid=validation_result)
        mock_adapter.build_query.return_value = f"SELECT * FROM {name}_table"
        return mock_adapter

    def _create_test_conversion_goal(self, goal_id: str = "test_goal") -> ConversionGoalFilter1:
        """Create a test conversion goal"""
        return ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id=goal_id,
            conversion_goal_name="Test Goal",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

    def test_initialization_basic(self):
        runner = self._create_query_runner()

        assert runner.query == self.default_query
        assert runner.team == self.team
        assert runner.paginator is not None
        assert runner.paginator.limit == DEFAULT_LIMIT
        assert runner.paginator.offset == 0

    def test_initialization_with_custom_pagination(self):
        custom_query = MarketingAnalyticsTableQuery(
            dateRange=self.default_date_range,
            limit=50,
            offset=25,
            properties=[],
        )
        runner = self._create_query_runner(custom_query)

        assert runner.paginator.limit == 50
        assert runner.paginator.offset == 25

    def test_query_date_range_property(self):
        runner = self._create_query_runner()
        date_range = runner.query_date_range

        assert isinstance(date_range, QueryDateRange)
        assert date_range.date_from_str.startswith("2023-01-01")
        assert date_range.date_to_str.startswith("2023-01-31")

    @patch(
        "products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner.MarketingSourceFactory"
    )
    def test_get_marketing_source_adapters_success(self, mock_factory_class):
        mock_factory = Mock()
        mock_factory_class.return_value = mock_factory

        mock_adapter1 = self._create_mock_adapter("GoogleAds", True)
        mock_adapter2 = self._create_mock_adapter("FacebookAds", True)

        mock_factory.create_adapters.return_value = [mock_adapter1, mock_adapter2]
        mock_factory.get_valid_adapters.return_value = [mock_adapter1, mock_adapter2]

        runner = self._create_query_runner()
        adapters = runner._get_marketing_source_adapters(runner.query_date_range)

        assert len(adapters) == 2
        assert adapters[0] == mock_adapter1
        assert adapters[1] == mock_adapter2

    @patch(
        "products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner.MarketingSourceFactory"
    )
    def test_get_marketing_source_adapters_exception_handling(self, mock_factory_class):
        mock_factory = Mock()
        mock_factory_class.return_value = mock_factory
        mock_factory.create_adapters.side_effect = Exception("Factory error")

        runner = self._create_query_runner()
        adapters = runner._get_marketing_source_adapters(runner.query_date_range)

        assert adapters == []

    def test_get_team_conversion_goals_empty(self):
        runner = self._create_query_runner()
        goals = runner._get_team_conversion_goals()

        assert goals == []

    def test_get_team_conversion_goals_with_draft_goal(self):
        conversion_goal = self._create_test_conversion_goal()
        query = MarketingAnalyticsTableQuery(
            dateRange=self.default_date_range,
            draftConversionGoal=conversion_goal,
            properties=[],
        )
        runner = self._create_query_runner(query)
        goals = runner._get_team_conversion_goals()

        assert len(goals) == 1
        assert goals[0] == conversion_goal

    def test_to_query_basic(self):
        with patch.object(MarketingAnalyticsTableQueryRunner, "_get_marketing_source_adapters") as mock_get_adapters:
            mock_get_adapters.return_value = []

            runner = self._create_query_runner()
            query = runner.to_query()

            assert isinstance(query, ast.SelectQuery)
            assert query.select is not None
            assert query.select_from is not None

    def test_calculate_basic(self):
        with patch.object(MarketingAnalyticsTableQueryRunner, "to_query") as mock_to_query:
            mock_to_query.return_value = ast.SelectQuery(
                select=[ast.Alias(alias="Campaign", expr=ast.Field(chain=["campaign"]))],
                select_from=ast.JoinExpr(table=ast.Field(chain=["test_table"])),
            )

            with patch("posthog.hogql.query.execute_hogql_query") as mock_execute:
                mock_execute.return_value = Mock(
                    results=[["test_campaign"]], types=[], hogql="SELECT campaign", timings=[]
                )

                runner = self._create_query_runner()
                result = runner.calculate()

                assert isinstance(result, MarketingAnalyticsTableQueryResponse)
                # Results are now transformed to WebAnalyticsItemBase objects
                assert len(result.results) == 1
                assert len(result.results[0]) == 1
                # Check the transformed item structure (should be WebAnalyticsItemBase)
                transformed_item = result.results[0][0]
                assert transformed_item.key == "Campaign"
                assert transformed_item.value == "test_campaign"
                assert transformed_item.previous is None
                assert transformed_item.kind == "unit"
                assert transformed_item.isIncreaseBad is False
                assert result.hasMore is False
                assert result.limit == DEFAULT_LIMIT
                assert result.offset == 0
