import pytest
from freezegun import freeze_time
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    events_cache_tests,
    persons_cache_tests,
)

from posthog.schema import (
    AttributionMode,
    BaseMathType,
    ConversionGoalFilter1,
    ConversionGoalFilter2,
    ConversionGoalFilter3,
    DateRange,
    EventPropertyFilter,
    NodeKind,
    PropertyMathType,
    PropertyOperator,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_in_tests

from posthog.models import Action
from posthog.models.event.util import bulk_create_events
from posthog.models.person.util import bulk_create_persons

from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import (
    ConversionGoalProcessor,
    add_conversion_goal_property_filters,
)
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_config import MarketingAnalyticsConfig


def _create_action(**kwargs):
    """Helper to create Action objects for testing"""
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    event_name = kwargs.pop("event_name", name)
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": event_name, "properties": properties}])
    return action


def flush_persons_and_events_in_batches(batch_size: int = 25):
    """
    Custom flush function that processes events in smaller batches to avoid memory limits.
    This helps prevent ClickHouse memory exceeded errors during bulk inserts.
    """
    person_mapping = {}
    if len(persons_cache_tests) > 0:
        person_mapping = bulk_create_persons(persons_cache_tests)
        persons_cache_tests.clear()

    if len(events_cache_tests) > 0:
        # Process events in smaller batches to avoid memory issues
        for i in range(0, len(events_cache_tests), batch_size):
            batch = events_cache_tests[i : i + batch_size]
            bulk_create_events(batch, person_mapping)
        events_cache_tests.clear()


class TestConversionGoalProcessor(ClickhouseTestMixin, BaseTest):
    """
    Comprehensive test suite for ConversionGoalProcessor.

    Test Coverage:
    - Basic functionality and initialization
    - Node type handling (EventsNode, ActionsNode, DataWarehouseNode)
    - Math type operations (TOTAL, DAU, SUM, etc.)
    - Property filtering and schema mapping
    - Query generation (CTE, JOIN, SELECT)
    - Error handling and edge cases
    - Integration testing with full query execution
    - Temporal attribution logic
    - Customer journey attribution scenarios
    - Data quality edge cases

    UTM Attribution Rules:
    - UTM parameters are only considered for attribution when they appear on $pageview events
    - UTM parameters on other events (sign_up, purchase, etc.) are ignored for attribution
    - This reflects standard marketing analytics behavior where UTM parameters represent
      the landing page visit from a marketing campaign, not subsequent user actions

    Attribution Validation Patterns:
    - Forward Order (Ad → Conversion): Should attribute correctly
    - Backward Order (Conversion → Ad): Should show Unknown attribution
    - Last-Touch Attribution: Should attribute to most recent valid touchpoint
    - Mixed Timeline: Only ads before conversion should be considered
    - Pageview Only: Only $pageview events with UTM parameters count for attribution

    Query Result Structure: [campaign_name, source_name, conversion_count]
    """

    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False  # Prevents test contamination in ClickHouse

    def setUp(self):
        super().setUp()
        # Ensure clean state before each test to prevent memory accumulation
        flush_persons_and_events_in_batches()
        self.date_range = DateRange(date_from="2023-01-01", date_to="2023-01-31")
        self.config = MarketingAnalyticsConfig.from_team(self.team)
        # No shared test data - each test creates its own isolated data

    def tearDown(self):
        # Ensure clean state after each test to prevent memory accumulation
        flush_persons_and_events_in_batches()
        super().tearDown()

    def _create_test_data(self):
        """Create comprehensive test data covering various scenarios"""
        with freeze_time("2023-01-15"):
            # Basic users
            _create_person(distinct_ids=["user1"], team=self.team, properties={"$browser": "Chrome"})
            _create_person(distinct_ids=["user2"], team=self.team, properties={"$browser": "Firefox"})
            _create_person(distinct_ids=["user3"], team=self.team, properties={"$browser": "Safari"})

            # User with UTM data
            _create_event(
                distinct_id="user1",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "google", "revenue": 100},
            )
            _create_event(
                distinct_id="user1",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "google", "revenue": 250},
            )

            # User with different UTM data
            _create_event(
                distinct_id="user2",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "winter_promo", "utm_source": "facebook", "revenue": 150},
            )

            # User without UTM data (edge case)
            _create_event(distinct_id="user3", event="newsletter_signup", team=self.team, properties={"revenue": 50})

            # High-value events for sum testing
            _create_event(
                distinct_id="user1",
                event="premium_purchase",
                team=self.team,
                properties={"revenue": 1000, "utm_campaign": "premium_push", "utm_source": "email"},
            )

            flush_persons_and_events_in_batches()

    # ================================================================
    # 1. BASIC UNIT TESTS - Core functionality
    # ================================================================

    def test_processor_basic_properties(self):
        """Test basic processor properties and initialization"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="signup_goal",
            conversion_goal_name="Sign Ups",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        # Test basic getters
        assert processor.get_cte_name() == "signup_goal"
        assert processor.get_table_name() == "events"
        assert processor.get_date_field() == "events.timestamp"
        assert isinstance(processor.goal, ConversionGoalFilter1)
        assert processor.index == 0

    def test_processor_index_variations(self):
        """Test processor behavior with different index values"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="test_event",
            conversion_goal_id="test",
            conversion_goal_name="Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        # Test various index values
        for index in [0, 1, 5, 10]:
            processor = ConversionGoalProcessor(goal=goal, index=index, team=self.team, config=self.config)
            join_clause = processor.generate_join_clause()
            assert join_clause.alias == f"cg_{index}"

    # ================================================================
    # 2. NODE TYPE TESTS - EventsNode, ActionsNode, DataWarehouseNode
    # ================================================================

    def test_events_node_basic(self):
        """Test basic EventsNode functionality"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="events_basic",
            conversion_goal_name="Events Basic",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        assert processor.get_table_name() == "events"
        conditions = processor.get_base_where_conditions()
        assert len(conditions) == 1  # event filter only

    def test_actions_node_basic(self):
        """Test basic ActionsNode functionality"""
        action = _create_action(team=self.team, name="Test Action", event_name="sign_up")

        goal = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id=str(action.id),
            conversion_goal_id="actions_basic",
            conversion_goal_name="Actions Basic",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        assert processor.get_table_name() == "events"
        conditions = processor.get_base_where_conditions()
        assert len(conditions) == 1  # action condition only

    def test_data_warehouse_node_basic(self):
        """Test basic DataWarehouseNode functionality"""
        goal = ConversionGoalFilter3(
            kind=NodeKind.DATA_WAREHOUSE_NODE,
            id="warehouse_id",
            table_name="warehouse_table",
            conversion_goal_id="warehouse_basic",
            conversion_goal_name="Warehouse Basic",
            math=BaseMathType.TOTAL,
            distinct_id_field="user_id",
            id_field="user_id",
            timestamp_field="event_timestamp",
            schema_map={
                "utm_campaign_name": "campaign_name",
                "utm_source_name": "source_name",
                "distinct_id_field": "user_id",
                "timestamp_field": "event_timestamp",
            },
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        assert processor.get_table_name() == "warehouse_table"
        assert processor.get_date_field() == "event_timestamp"

    # ================================================================
    # 3. MATH TYPE TESTS - TOTAL, DAU, SUM, etc.
    # ================================================================

    def test_math_type_total_counts_all_events_correctly(self):
        """Test TOTAL math type correctly counts all events - business logic validation"""

        # Create test data: multiple events per user to test total count vs unique users
        with freeze_time("2023-01-15"):
            # User1: 3 sign_ups (should count as 3 total events)
            _create_person(distinct_ids=["total_test_user1"], team=self.team)
            _create_event(
                distinct_id="total_test_user1",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "growth_hack", "utm_source": "twitter"},
            )
            _create_event(
                distinct_id="total_test_user1",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "growth_hack", "utm_source": "twitter"},
            )
            _create_event(
                distinct_id="total_test_user1",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "growth_hack", "utm_source": "twitter"},
            )

            # User2: 2 sign_ups (should count as 2 total events)
            _create_person(distinct_ids=["total_test_user2"], team=self.team)
            _create_event(
                distinct_id="total_test_user2",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "growth_hack", "utm_source": "twitter"},
            )
            _create_event(
                distinct_id="total_test_user2",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "growth_hack", "utm_source": "twitter"},
            )

            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="total_business_test",
            conversion_goal_name="Total Business Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]

        # Execute the full query and validate business logic
        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert response is not None
        assert len(response.results) == 1

        # Get our test result directly since it's the only one
        campaign_name, source_name, total_count = response.results[0][0], response.results[0][1], response.results[0][2]

        # Validation: TOTAL should count all 5 events (3+2), not unique users
        assert campaign_name == "growth_hack"
        assert source_name == "twitter"
        assert (
            total_count == 5
        ), f"Expected total count of 5 events (3+2), got {total_count}. TOTAL should count all events, not unique users."

    def test_math_type_dau_counts_unique_users_correctly(self):
        """Test DAU math type correctly counts unique users - business logic validation"""

        # Create test data: 3 users with different patterns
        with freeze_time("2023-01-15"):
            # User1: 3 sign_ups (should count as 1 unique user)
            _create_person(distinct_ids=["dau_test_user1"], team=self.team)
            _create_event(
                distinct_id="dau_test_user1",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "test_campaign", "utm_source": "google"},
            )
            _create_event(
                distinct_id="dau_test_user1",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "test_campaign", "utm_source": "google"},
            )
            _create_event(
                distinct_id="dau_test_user1",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "test_campaign", "utm_source": "google"},
            )

            # User2: 1 sign_up (should count as 1 unique user)
            _create_person(distinct_ids=["dau_test_user2"], team=self.team)
            _create_event(
                distinct_id="dau_test_user2",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "test_campaign", "utm_source": "google"},
            )

            # User3: 2 sign_ups (should count as 1 unique user)
            _create_person(distinct_ids=["dau_test_user3"], team=self.team)
            _create_event(
                distinct_id="dau_test_user3",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "test_campaign", "utm_source": "google"},
            )
            _create_event(
                distinct_id="dau_test_user3",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "test_campaign", "utm_source": "google"},
            )

            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="dau_business_test",
            conversion_goal_name="DAU Business Test",
            math=BaseMathType.DAU,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]

        # Execute the full query and validate business logic
        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert response is not None
        assert len(response.results) == 1

        # Get our test result directly since it's the only one
        campaign_name, source_name, dau_count = response.results[0][0], response.results[0][1], response.results[0][2]

        # Validation: DAU should count 3 unique users, not 6 total events
        assert campaign_name == "test_campaign"
        assert source_name == "google"
        assert (
            dau_count == 3
        ), f"Expected 3 unique users (DAU), got {dau_count}. Total events were 6, but DAU should count unique users."

    def test_math_type_sum_correctly_adds_revenue_values(self):
        """Test SUM math type correctly adds revenue property values - business logic validation"""

        # Create test data: purchases with different revenue amounts
        with freeze_time("2023-01-15"):
            # User1: $100 purchase
            _create_person(distinct_ids=["sum_test_buyer1"], team=self.team)
            _create_event(
                distinct_id="sum_test_buyer1",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "facebook", "revenue": 100},
            )
            _create_event(
                distinct_id="sum_test_buyer1",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "facebook", "revenue": 0},
            )
            _create_event(
                distinct_id="sum_test_buyer1",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "facebook"},
            )

            # User2: $250 purchase
            _create_person(distinct_ids=["sum_test_buyer2"], team=self.team)
            _create_event(
                distinct_id="sum_test_buyer2",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "facebook", "revenue": 250},
            )

            # User3: $50 purchase
            _create_person(distinct_ids=["sum_test_buyer3"], team=self.team)
            _create_event(
                distinct_id="sum_test_buyer3",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "facebook", "revenue": 50},
            )

            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="sum_business_test",
            conversion_goal_name="Sum Business Test",
            math=PropertyMathType.SUM,
            math_property="revenue",
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]

        # Execute the full query and validate business logic
        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert response is not None
        assert len(response.results) == 1

        # Get our test result directly since it's the only one
        campaign_name, source_name, total_revenue = (
            response.results[0][0],
            response.results[0][1],
            response.results[0][2],
        )

        # Validation: SUM should add all revenue values (100 + 0 + missing=0 + 250 + 50 = 400)
        assert campaign_name == "summer_sale"
        assert source_name == "meta"
        assert (
            total_revenue == 400
        ), f"Expected total revenue of 400 (100+0+missing=0+250+50), got {total_revenue}. Missing revenue should be treated as 0."

    def test_math_type_sum_handles_missing_and_zero_values_correctly(self):
        """Test SUM math type correctly handles missing properties and zero values - business logic validation"""

        # Create test data: events with different revenue scenarios
        with freeze_time("2023-01-15"):
            # User1: Mix of valid, zero, and missing revenue values
            _create_person(distinct_ids=["sum_missing_test_user1"], team=self.team)
            _create_event(
                distinct_id="sum_missing_test_user1",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "edge_case_test", "utm_source": "test", "revenue": 100},
            )
            _create_event(
                distinct_id="sum_missing_test_user1",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "edge_case_test", "utm_source": "test", "revenue": 0},
            )
            _create_event(
                distinct_id="sum_missing_test_user1",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "edge_case_test", "utm_source": "test"},
            )  # No revenue property

            # User2: Only missing revenue property
            _create_person(distinct_ids=["sum_missing_test_user2"], team=self.team)
            _create_event(
                distinct_id="sum_missing_test_user2",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "edge_case_test", "utm_source": "test"},
            )  # No revenue property

            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="sum_missing_business_test",
            conversion_goal_name="Sum Missing Business Test",
            math=PropertyMathType.SUM,
            math_property="revenue",
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]

        # Execute the full query and validate business logic
        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert response is not None
        assert len(response.results) == 1

        # Get our test result directly since it's the only one
        campaign_name, source_name, total_revenue = (
            response.results[0][0],
            response.results[0][1],
            response.results[0][2],
        )

        # Validation: SUM should handle missing values as 0 (100 + 0 + 0 + 0 = 100)
        assert campaign_name == "edge_case_test"
        assert source_name == "test"
        assert (
            total_revenue == 100
        ), f"Expected total revenue of 100 (100+0+missing=0+missing=0), got {total_revenue}. Missing revenue properties should be treated as 0."

    def test_math_type_average_fallback_behavior(self):
        """Test AVERAGE math type fallback behavior - counts events since AVG not implemented - business logic validation"""

        # Create test data: events to test AVG fallback behavior
        with freeze_time("2023-01-15"):
            # User1: 2 purchase events (should count as 2 events, not average revenue)
            _create_person(distinct_ids=["avg_test_user1"], team=self.team)
            _create_event(
                distinct_id="avg_test_user1",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "avg_fallback_test", "utm_source": "test", "revenue": 100},
            )
            _create_event(
                distinct_id="avg_test_user1",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "avg_fallback_test", "utm_source": "test", "revenue": 300},
            )

            # User2: 1 purchase event
            _create_person(distinct_ids=["avg_test_user2"], team=self.team)
            _create_event(
                distinct_id="avg_test_user2",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "avg_fallback_test", "utm_source": "test", "revenue": 200},
            )

            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="avg_fallback_business_test",
            conversion_goal_name="Avg Fallback Business Test",
            math=PropertyMathType.AVG,
            math_property="revenue",
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]

        # Execute the full query and validate business logic
        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert response is not None
        assert len(response.results) == 1

        # Get our test result directly since it's the only one
        campaign_name, source_name, result_value = (
            response.results[0][0],
            response.results[0][1],
            response.results[0][2],
        )

        # Validation: AVG fallback should count 3 events, NOT average revenue (200)
        assert campaign_name == "avg_fallback_test"
        assert source_name == "test"
        assert (
            result_value == 3
        ), f"Expected count of 3 events (AVG fallback), got {result_value}. AVG is not implemented so it falls back to counting events, not averaging revenue values."

    # ================================================================
    # 4. PROPERTY FILTER TESTS - Event properties, filters
    # ================================================================

    def test_property_filters_actually_filter_events_correctly(self):
        """Test property filters actually filter events based on numeric conditions (>= operator) - business logic validation"""

        # Create test data: purchases with different revenue amounts
        with freeze_time("2023-01-15"):
            # User1: revenue=75 (should be EXCLUDED by revenue >= 100 filter)
            _create_person(distinct_ids=["filter_test_buyer1"], team=self.team)
            _create_event(
                distinct_id="filter_test_buyer1",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "filter_test", "utm_source": "test", "revenue": "075"},
            )

            # User2: revenue=100 (should be INCLUDED by revenue >= 100 filter)
            _create_person(distinct_ids=["filter_test_buyer2"], team=self.team)
            _create_event(
                distinct_id="filter_test_buyer2",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "filter_test", "utm_source": "test", "revenue": "100"},
            )

            # User3: revenue=150 (should be INCLUDED by revenue >= 100 filter)
            _create_person(distinct_ids=["filter_test_buyer3"], team=self.team)
            _create_event(
                distinct_id="filter_test_buyer3",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "filter_test", "utm_source": "test", "revenue": "150"},
            )

            # User4: revenue=50 (should be EXCLUDED by revenue >= 100 filter)
            _create_person(distinct_ids=["filter_test_buyer4"], team=self.team)
            _create_event(
                distinct_id="filter_test_buyer4",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "filter_test", "utm_source": "test", "revenue": "050"},
            )

            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="filter_business_test",
            conversion_goal_name="Filter Business Test",
            math=BaseMathType.TOTAL,
            properties=[EventPropertyFilter(key="revenue", operator=PropertyOperator.GTE, value="100", type="event")],
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]

        # Apply property filters to conditions
        full_conditions = additional_conditions.copy()
        full_conditions = add_conversion_goal_property_filters(full_conditions, goal, self.team)

        # Execute the full query and validate business logic
        cte_query = processor.generate_cte_query(full_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert response is not None
        assert len(response.results) == 1  # Only our test data

        # Get our test result directly since it's the only one
        campaign_name, source_name, filtered_count = (
            response.results[0][0],
            response.results[0][1],
            response.results[0][2],
        )

        # Validation: Should only count 2 events (revenue >= 100), not all 4
        assert campaign_name == "filter_test"
        assert source_name == "test"
        assert (
            filtered_count == 2
        ), f"Expected 2 events with revenue >= 100 (100, 150), got {filtered_count}. Filter should exclude events with revenue < 100 (50, 75)."

    def test_property_filters_multiple_filters(self):
        """Test ConversionGoalProcessor query correctly filters events with multiple property conditions"""

        with freeze_time("2023-01-15"):
            # User1: High revenue + correct source (should MATCH both filters)
            _create_person(distinct_ids=["multi_filter_user1"], team=self.team)
            _create_event(
                distinct_id="multi_filter_user1",
                event="purchase",
                team=self.team,
                properties={"revenue": "150", "utm_campaign": "multi_filter_test", "utm_source": "google"},
            )

            # User2: Low revenue + correct source (should NOT match - revenue <= 100)
            _create_person(distinct_ids=["multi_filter_user2"], team=self.team)
            _create_event(
                distinct_id="multi_filter_user2",
                event="purchase",
                team=self.team,
                properties={"revenue": "050", "utm_campaign": "multi_filter_test", "utm_source": "google"},
            )

            # User3: High revenue + wrong source (should NOT match - wrong source)
            _create_person(distinct_ids=["multi_filter_user3"], team=self.team)
            _create_event(
                distinct_id="multi_filter_user3",
                event="purchase",
                team=self.team,
                properties={"revenue": "200", "utm_campaign": "multi_filter_test", "utm_source": "facebook"},
            )

            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multi_filter",
            conversion_goal_name="Multi Filter",
            math=BaseMathType.TOTAL,
            properties=[
                EventPropertyFilter(key="revenue", operator=PropertyOperator.GT, value="100", type="event"),
                EventPropertyFilter(key="utm_source", operator=PropertyOperator.EXACT, value="google", type="event"),
            ],
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        # Apply property filters to additional conditions (same pattern as working test)
        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]
        full_conditions = additional_conditions.copy()
        full_conditions = add_conversion_goal_property_filters(full_conditions, goal, self.team)

        # Generate and execute the ConversionGoalProcessor query
        cte_query = processor.generate_cte_query(full_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Should find exactly 1 result: only event 1 matches both filters
        assert len(response.results) == 1, f"Expected 1 event matching both filters, got {len(response.results)}"

        # Result format: [campaign_name, source_name, conversion_count]
        campaign_name, source_name, conversion_count = (
            response.results[0][0],
            response.results[0][1],
            response.results[0][2],
        )

        assert campaign_name == "multi_filter_test"
        assert source_name == "google"
        assert (
            conversion_count == 1
        ), f"Expected conversion count of 1, got {conversion_count}. Only event 1 should match both revenue > 100 AND utm_source = 'google'."

    def test_property_filters_complex_operators(self):
        """Test complex property filter operators LT and ICONTAINS work correctly together"""

        with freeze_time("2023-01-15"):
            # User1: Low revenue + campaign contains "sale" (should MATCH both filters)
            _create_person(distinct_ids=["complex_user1"], team=self.team)
            _create_event(
                distinct_id="complex_user1",
                event="purchase",
                team=self.team,
                properties={"revenue": "300", "utm_campaign": "summer_SALE_promo", "utm_source": "test"},
            )

            # User2: High revenue + campaign contains "sale" (should NOT match - revenue >= 500)
            _create_person(distinct_ids=["complex_user2"], team=self.team)
            _create_event(
                distinct_id="complex_user2",
                event="purchase",
                team=self.team,
                properties={"revenue": "600", "utm_campaign": "mega_sale_event", "utm_source": "test"},
            )

            # User3: Low revenue + campaign does NOT contain "sale" (should NOT match - no "sale")
            _create_person(distinct_ids=["complex_user3"], team=self.team)
            _create_event(
                distinct_id="complex_user3",
                event="purchase",
                team=self.team,
                properties={"revenue": "200", "utm_campaign": "winter_promo", "utm_source": "test"},
            )

            # User4: High revenue + no "sale" (should NOT match - fails both filters)
            _create_person(distinct_ids=["complex_user4"], team=self.team)
            _create_event(
                distinct_id="complex_user4",
                event="purchase",
                team=self.team,
                properties={"revenue": "800", "utm_campaign": "premium_launch", "utm_source": "test"},
            )

            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="complex_filter",
            conversion_goal_name="Complex Filter",
            math=BaseMathType.TOTAL,
            properties=[
                EventPropertyFilter(key="revenue", operator=PropertyOperator.LT, value="500", type="event"),
                EventPropertyFilter(
                    key="utm_campaign", operator=PropertyOperator.ICONTAINS, value="sale", type="event"
                ),
            ],
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        # Apply property filters to additional conditions (same pattern as working test)
        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]
        full_conditions = additional_conditions.copy()
        full_conditions = add_conversion_goal_property_filters(full_conditions, goal, self.team)

        # Generate and execute the ConversionGoalProcessor query
        cte_query = processor.generate_cte_query(full_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Should find exactly 1 result: only user1 matches both revenue < 500 AND campaign ICONTAINS "sale"
        assert (
            len(response.results) == 1
        ), f"Expected 1 event matching both complex filters, got {len(response.results)}"

        # Result format: [campaign_name, source_name, conversion_count]
        campaign_name, source_name, conversion_count = (
            response.results[0][0],
            response.results[0][1],
            response.results[0][2],
        )

        assert campaign_name == "summer_SALE_promo"
        assert source_name == "test"
        assert (
            conversion_count == 1
        ), f"Expected conversion count of 1, got {conversion_count}. Only user1 should match both revenue < 500 AND campaign contains 'sale' (case-insensitive)."

    # ================================================================
    # 5. SCHEMA MAPPING TESTS - UTM expressions, field mappings
    # ================================================================

    def test_utm_expressions_events_node(self):
        """Test UTM expressions for EventsNode"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="utm_events",
            conversion_goal_name="UTM Events",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        utm_campaign, utm_source = processor.get_utm_expressions()
        assert utm_campaign.chain == ["events", "properties", "utm_campaign"]
        assert utm_source.chain == ["events", "properties", "utm_source"]

    def test_utm_expressions_data_warehouse_node(self):
        """Test UTM expressions for DataWarehouseNode"""
        goal = ConversionGoalFilter3(
            kind=NodeKind.DATA_WAREHOUSE_NODE,
            id="warehouse_utm",
            table_name="warehouse_table",
            conversion_goal_id="utm_warehouse",
            conversion_goal_name="UTM Warehouse",
            math=BaseMathType.TOTAL,
            distinct_id_field="user_id",
            id_field="user_id",
            timestamp_field="created_at",
            schema_map={
                "utm_campaign_name": "campaign_field",
                "utm_source_name": "source_field",
                "distinct_id_field": "user_id",
                "timestamp_field": "created_at",
            },
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        utm_campaign, utm_source = processor.get_utm_expressions()
        assert utm_campaign.chain == ["campaign_field"]
        assert utm_source.chain == ["source_field"]

    def test_schema_mapping_custom_fields(self):
        """Test custom field mappings in schema_map"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="custom_schema",
            conversion_goal_name="Custom Schema",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "custom_campaign_field", "utm_source_name": "custom_source_field"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        utm_campaign, utm_source = processor.get_utm_expressions()
        assert utm_campaign.chain == ["events", "properties", "custom_campaign_field"]
        assert utm_source.chain == ["events", "properties", "custom_source_field"]

    def test_schema_mapping_missing_fields(self):
        """Test behavior when schema_map is missing required fields - should fallback gracefully"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="missing_schema",
            conversion_goal_name="Missing Schema",
            math=BaseMathType.TOTAL,
            schema_map={},  # Empty schema map
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        # Should handle missing schema gracefully and fallback to defaults
        utm_campaign, utm_source = processor.get_utm_expressions()
        assert utm_campaign is not None
        assert utm_source is not None

        # Verify fallback to default field names
        assert utm_campaign.chain == ["events", "properties", "utm_campaign"]
        assert utm_source.chain == ["events", "properties", "utm_source"]

    def test_schema_mapping_custom_fields_end_to_end_attribution(self):
        """
        Test that custom schema mapping works end-to-end for attribution

        This test validates that the schema_map logic actually works in practice,
        not just for building expressions. It would fail if the custom field mapping
        logic in the processor wasn't working properly.
        """
        # Create events with UTM data stored in CUSTOM field names
        with freeze_time("2023-04-15"):
            _create_person(distinct_ids=["custom_fields_user"], team=self.team)
            _create_event(
                distinct_id="custom_fields_user",
                event="$pageview",
                team=self.team,
                properties={
                    # Store UTM data in custom field names (not default utm_campaign/utm_source)
                    "my_campaign_field": "custom_campaign_test",
                    "my_source_field": "custom_source_test",
                    # Also include default fields with different values to ensure they're ignored
                    "utm_campaign": "default_campaign_should_be_ignored",
                    "utm_source": "default_source_should_be_ignored",
                },
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-10"):
            _create_event(
                distinct_id="custom_fields_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events_in_batches()

        # Configure processor to use CUSTOM field mappings
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="custom_fields_attribution",
            conversion_goal_name="Custom Fields Attribution",
            math=BaseMathType.TOTAL,
            # Map to our custom field names (this is the logic being tested!)
            schema_map={"utm_campaign_name": "my_campaign_field", "utm_source_name": "my_source_field"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        # Execute the full query with custom schema mapping
        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Validate that attribution worked with custom field names
        assert response is not None
        assert len(response.results) == 1

        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]

        # Validation: Should use data from custom fields, not default fields
        assert campaign_name == "custom_campaign_test", (
            f"Should use custom field 'my_campaign_field', got {campaign_name}. "
            f"If this fails, schema_map logic is broken!"
        )
        assert source_name == "custom_source_test", (
            f"Should use custom field 'my_source_field', got {source_name}. "
            f"If this fails, schema_map logic is broken!"
        )
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

        # Verify it did NOT use the default field values
        assert campaign_name != "default_campaign_should_be_ignored"
        assert source_name != "default_source_should_be_ignored"

    # ================================================================
    # 6. QUERY GENERATION TESTS - CTE, JOIN, SELECT
    # ================================================================

    def test_generate_join_clause_structure(self):
        """Test JOIN clause generation structure"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="join_test",
            conversion_goal_name="Join Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        join_clause = processor.generate_join_clause()
        assert join_clause.join_type == "LEFT JOIN"
        assert join_clause.alias == "cg_0"
        assert join_clause.constraint.constraint_type == "ON"
        assert isinstance(join_clause.constraint.expr, ast.And)

    def test_generate_select_columns_structure(self):
        """Test SELECT columns generation structure"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="select_test",
            conversion_goal_name="Select Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        select_columns = processor.generate_select_columns()
        assert len(select_columns) == 2

        # First column: conversion goal value
        assert select_columns[0].alias == "Select Test"

        # Second column: cost per conversion goal
        assert select_columns[1].alias == "Cost per Select Test"
        assert isinstance(select_columns[1].expr, ast.Call)
        assert select_columns[1].expr.name == "round"

    # ================================================================
    # 7. ERROR HANDLING TESTS - Missing data, invalid configs
    # ================================================================

    def test_error_missing_action(self):
        """Test error handling when Action doesn't exist"""
        goal = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id="999999",
            conversion_goal_id="missing_action",
            conversion_goal_name="Missing Action",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        with pytest.raises(Action.DoesNotExist):
            processor.get_base_where_conditions()

    def test_error_invalid_math_property_combination(self):
        """Test graceful handling of invalid math+property combinations"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="invalid_combo",
            conversion_goal_name="Invalid Combo",
            math=BaseMathType.DAU,
            math_property="revenue",  # Invalid combo
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        # Should handle gracefully by ignoring irrelevant math_property for DAU
        select_field = processor.get_select_field()
        assert select_field is not None

        # DAU should ignore math_property and use uniq(distinct_id)
        assert isinstance(select_field, ast.Call)
        assert select_field.name == "uniq"
        assert select_field.args[0].chain == ["events", "distinct_id"]

    def test_error_empty_event_name(self):
        """Test what actually happens when we execute query with empty event name"""

        with freeze_time("2023-01-15"):
            # Create different event types to see what gets matched with empty event name
            _create_person(distinct_ids=["empty_test_user1"], team=self.team)
            _create_event(
                distinct_id="empty_test_user1",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "empty_test", "revenue": "100"},
            )

            _create_person(distinct_ids=["empty_test_user2"], team=self.team)
            _create_event(
                distinct_id="empty_test_user2",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "empty_test", "revenue": "200"},
            )

            _create_person(distinct_ids=["empty_test_user3"], team=self.team)
            _create_event(
                distinct_id="empty_test_user3",
                event="page_view",
                team=self.team,
                properties={"utm_campaign": "empty_test", "revenue": "300"},
            )

            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="",  # Empty event name
            conversion_goal_id="empty_event",
            conversion_goal_name="Empty Event",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]
        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # If it succeeds, check results - result format: [campaign_name, source_name, conversion_count]
        total_conversions = sum(row[2] for row in response.results)
        assert (
            total_conversions == 3
        ), f"Expected 3 total conversions (all events) with empty event name, got {total_conversions}"

    # ================================================================
    # 8. EDGE CASE TESTS - Complex scenarios
    # ================================================================

    def test_edge_case_very_long_goal_names(self):
        """Test that queries work correctly with very long goal names"""

        with freeze_time("2023-01-15"):
            # Create test event for very long goal name
            _create_person(distinct_ids=["long_name_user"], team=self.team)
            _create_event(
                distinct_id="long_name_user",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "long_name_test", "revenue": "100"},
            )

            flush_persons_and_events_in_batches()

        long_name = "A" * 1000  # Very long goal name (1000 characters)

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="long_name",
            conversion_goal_name=long_name,
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        # Test that query executes successfully with very long goal name
        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]
        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Should find 1 event and handle long name without truncation or errors
        assert len(response.results) == 1, f"Expected 1 event with very long goal name, got {len(response.results)}"

        # Result format: [campaign_name, source_name, conversion_count]
        campaign_name, source_name, conversion_count = (
            response.results[0][0],
            response.results[0][1],
            response.results[0][2],
        )

        assert campaign_name == "long_name_test"
        assert source_name == "organic", f"Expected organic source, got {source_name}"
        assert (
            conversion_count == 1
        ), f"Expected conversion count of 1 with very long goal name, got {conversion_count}. Long names should not affect query results."

    def test_edge_case_special_characters_in_event_names(self):
        """Test that events with special characters in names are correctly matched"""

        with freeze_time("2023-01-15"):
            special_event = "event-with_special.chars@123!$%"  # Removed quotes/backslashes to avoid escaping issues

            # Create event with special characters in the name
            _create_person(distinct_ids=["special_chars_user"], team=self.team)
            _create_event(
                distinct_id="special_chars_user",
                event=special_event,
                team=self.team,
                properties={"utm_campaign": "special_test", "revenue": "100"},
            )

            # Create a normal event to ensure special chars don't match everything
            _create_person(distinct_ids=["normal_user"], team=self.team)
            _create_event(
                distinct_id="normal_user",
                event="normal_event",
                team=self.team,
                properties={"utm_campaign": "special_test", "revenue": "200"},
            )

            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event=special_event,
            conversion_goal_id="special_chars",
            conversion_goal_name="Special Chars",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        # Test that query correctly matches only the event with special characters
        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]
        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Should find exactly 1 event - only the one with special characters in name
        assert (
            len(response.results) == 1
        ), f"Expected 1 event with special characters in name, got {len(response.results)}"

        # Result format: [campaign_name, source_name, conversion_count]
        campaign_name, source_name, conversion_count = (
            response.results[0][0],
            response.results[0][1],
            response.results[0][2],
        )

        assert campaign_name == "special_test"
        assert source_name == "organic", f"Expected organic source, got {source_name}"
        assert (
            conversion_count == 1
        ), f"Expected conversion count of 1 for special character event, got {conversion_count}. Special characters in event names should be handled correctly."

    def test_edge_case_unicode_in_properties(self):
        """Test that Unicode property names work correctly in queries and attribution"""

        with freeze_time("2023-01-15"):
            # Create event with Unicode property names and values
            _create_person(distinct_ids=["unicode_user"], team=self.team)
            _create_event(
                distinct_id="unicode_user",
                event="sign_up",
                team=self.team,
                properties={
                    "营销活动": "春节促销",  # Chinese campaign name
                    "来源": "百度",  # Chinese source name
                    "revenue": "100",
                },
            )

            # Create event with ASCII properties to ensure Unicode doesn't break everything
            _create_person(distinct_ids=["ascii_user"], team=self.team)
            _create_event(
                distinct_id="ascii_user",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "ascii_campaign", "utm_source": "google", "revenue": "200"},
            )

            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="unicode_test",
            conversion_goal_name="Unicode Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "营销活动", "utm_source_name": "来源"},  # Chinese property names
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        # Test that query executes successfully with Unicode property names
        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]
        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Should find both events - Unicode property names should work without affecting results
        assert (
            len(response.results) == 2
        ), f"Expected 2 events with Unicode property mapping, got {len(response.results)}"

        # Check that both events are counted correctly - result format: [campaign_name, source_name, conversion_count]
        total_conversions = sum(row[2] for row in response.results)  # row[2] is conversion_count
        assert (
            total_conversions == 2
        ), f"Expected total of 2 conversions with Unicode properties, got {total_conversions}. Unicode property names should not affect conversion counting."

    def test_edge_case_temporal_attribution_complex_timeline(self):
        """Test that ConversionGoalProcessor correctly handles conversions with complex temporal scenarios"""

        # Create complex timeline: UTM before range → conversion in range → UTM after
        with freeze_time("2022-12-15"):
            _create_person(distinct_ids=["temporal_user"], team=self.team)
            _create_event(
                distinct_id="temporal_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "pre_range", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-01-10"):
            _create_event(
                distinct_id="temporal_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 100},  # No UTM on conversion
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-01-20"):
            _create_event(
                distinct_id="temporal_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "post_conversion", "utm_source": "facebook"},
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="temporal_complex",
            conversion_goal_name="Temporal Complex",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        # Test that query executes and finds the conversion despite complex timeline
        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]
        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Should find exactly 1 conversion despite complex UTM timeline
        assert len(response.results) == 1, f"Expected 1 conversion with complex timeline, got {len(response.results)}"

        # Result format: [campaign_name, source_name, conversion_count]
        campaign_name, source_name, conversion_count = (
            response.results[0][0],
            response.results[0][1],
            response.results[0][2],
        )

        assert (
            conversion_count == 1
        ), f"Expected 1 conversion despite complex timeline, got {conversion_count}. ConversionGoalProcessor should handle complex temporal scenarios correctly."
        assert campaign_name == "pre_range", f"Expected pre_range campaign, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"

    # ================================================================
    # 9. INTEGRATION TESTS - Full query execution with snapshots
    # ================================================================

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_integration_events_node_full_query_execution(self):
        """Integration test: Full EventsNode query execution with snapshot"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="integration_events",
            conversion_goal_name="Integration Events",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_integration_actions_node_full_query_execution(self):
        """Integration test: Full ActionsNode query execution with snapshot"""
        action = _create_action(team=self.team, name="Integration Action", event_name="sign_up")

        goal = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id=str(action.id),
            conversion_goal_id="integration_actions",
            conversion_goal_name="Integration Actions",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_integration_sum_math_full_query_execution(self):
        """Integration test: Full SUM math query execution with snapshot"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="integration_sum",
            conversion_goal_name="Integration Sum",
            math=PropertyMathType.SUM,
            math_property="revenue",
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    def test_integration_query_structure_validation(self):
        """Integration test: Validate overall query structure without execution"""
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="structure_test",
            conversion_goal_name="Structure Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        # Test all major components can be generated without errors
        assert processor.get_select_field() is not None
        assert processor.get_base_where_conditions() is not None
        assert processor.get_utm_expressions() is not None
        assert processor.generate_join_clause() is not None
        assert processor.generate_select_columns() is not None

    # ================================================================
    # 10. TEMPORAL ATTRIBUTION CORE TESTS - Ad timing vs conversion timing
    # ================================================================

    def test_temporal_attribution_basic_forward_order(self):
        """
        Test Case: Basic temporal attribution - Ad BEFORE conversion (SHOULD attribute)

        Scenario: User sees ad in April, converts in May
        Expected: Conversion should be attributed to the April ad
        Rule: Ads must come BEFORE conversions to get attribution credit
        """
        with freeze_time("2023-04-15"):
            _create_person(distinct_ids=["forward_user"], team=self.team)
            _create_event(
                distinct_id="forward_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "spring_sale", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-10"):
            _create_event(
                distinct_id="forward_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 100},  # No UTM on conversion event
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="temporal_forward",
            conversion_goal_name="Temporal Forward",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        # Execute query and verify attribution
        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert response is not None

        # Validation: Ad before conversion should attribute correctly
        # Expected attribution: spring_sale/google (from April ad)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "spring_sale", f"Expected spring_sale campaign, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_temporal_attribution_forward_order_validation_example(self):
        """
        EXAMPLE: How to validate attribution results properly

        This test shows the pattern for validating attribution results.
        """
        # Setup: Create ad touchpoint before conversion
        with freeze_time("2023-04-15"):
            _create_person(distinct_ids=["validation_user"], team=self.team)
            _create_event(
                distinct_id="validation_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "spring_sale", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-10"):
            _create_event(distinct_id="validation_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events_in_batches()

        # Create processor and execute query
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="validation_test",
            conversion_goal_name="Validation Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # 1. Basic response validation
        assert response is not None
        assert response.results is not None
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # 2. Expected result structure validation
        # The query returns: [campaign_name, source_name, conversion_count]
        first_result = response.results[0]

        # Validate attribution values (correct indices based on actual query structure)
        expected_campaign = "spring_sale"
        expected_source = "google"
        expected_conversion_count = 1

        # Correct assertions based on actual query result structure:
        # Index 0: campaign_name, Index 1: source_name, Index 2: conversion_count
        assert first_result[0] == expected_campaign, f"Expected campaign '{expected_campaign}', got '{first_result[0]}'"
        assert first_result[1] == expected_source, f"Expected source '{expected_source}', got '{first_result[1]}'"
        assert (
            first_result[2] == expected_conversion_count
        ), f"Expected {expected_conversion_count} conversion, got {first_result[2]}"

    def test_temporal_attribution_backward_order_validation_example(self):
        """
        Test that wrong temporal order produces Unknown attribution.

        Scenario: Conversion occurs before ad touchpoint
        Expected: Should show Unknown attribution since ad came after conversion
        """
        # Setup: Create conversion before ad touchpoint (wrong order)
        with freeze_time("2023-04-15"):
            _create_person(distinct_ids=["backward_validation_user"], team=self.team)
            _create_event(
                distinct_id="backward_validation_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 100},  # Conversion first
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-10"):
            _create_event(
                distinct_id="backward_validation_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "too_late", "utm_source": "google"},  # Ad after conversion
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="backward_validation",
            conversion_goal_name="Backward Validation",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Validation: Should show Unknown attribution since ad came after conversion
        assert response is not None
        assert len(response.results) == 1

        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]

        # Assert that attribution is Unknown because ad came after conversion
        assert campaign_name == "organic", f"Expected organic attribution, got {campaign_name}"
        assert source_name == "organic", f"Expected organic source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_multiple_touchpoints_attribution_validation_example(self):
        """
        Test multi-touch attribution with last-touch logic.

        Timeline: Email touchpoint → Facebook touchpoint → Purchase
        Expected: Should attribute to Facebook (last touchpoint before conversion)
        """
        # Setup: Create email touchpoint first
        with freeze_time("2023-04-01"):
            _create_person(distinct_ids=["multi_user"], team=self.team)
            _create_event(
                distinct_id="multi_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "newsletter", "utm_source": "email"},
            )
            flush_persons_and_events_in_batches()

        # Setup: Create Facebook touchpoint later (last touch)
        with freeze_time("2023-04-15"):
            _create_event(
                distinct_id="multi_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "spring_promo", "utm_source": "facebook"},
            )
            flush_persons_and_events_in_batches()

        # Conversion with no UTM (should use last touchpoint)
        with freeze_time("2023-05-10"):
            _create_event(distinct_id="multi_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events_in_batches()

        # Create processor and execute query
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multi_touch_test",
            conversion_goal_name="Multi Touch Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Validate basic response
        assert response is not None
        assert len(response.results) == 1

        # Validation: Last-touch attribution should choose Facebook over Email
        # Timeline: newsletter/email (Apr 1) → spring_promo/facebook (Apr 15) → purchase (May 10)
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]

        assert (
            campaign_name == "spring_promo"
        ), f"Last-touch attribution should choose Facebook campaign over Email, got {campaign_name}"
        assert source_name == "meta", f"Last-touch attribution should choose Meta source over Email, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_direct_utm_attribution_priority_over_temporal(self):
        """
        Note: Direct UTM params on conversion event should override temporal attribution

        Timeline:
        1. User sees ad1 (utm_campaign=summer_sale, utm_source=google)
        2. User sees ad2 (utm_campaign=flash_sale, utm_source=facebook)
        3. User converts WITH ad1 params directly on conversion event

        Expected: Attribution goes to ad1 (direct UTM) NOT ad2 (last temporal touchpoint)
        """
        # Setup: Create ad1 touchpoint first
        with freeze_time("2023-04-01"):
            _create_person(distinct_ids=["direct_utm_user"], team=self.team)
            _create_event(
                distinct_id="direct_utm_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        # Setup: Create ad2 touchpoint later (would be last touch temporally)
        with freeze_time("2023-04-15"):
            _create_event(
                distinct_id="direct_utm_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "flash_sale", "utm_source": "facebook"},
            )
            flush_persons_and_events_in_batches()

        # Note: Conversion event has ad1 UTM params directly
        # This should override temporal attribution to ad2
        with freeze_time("2023-05-10"):
            _create_event(
                distinct_id="direct_utm_user",
                event="purchase",
                team=self.team,
                properties={
                    "revenue": 100,
                    "utm_campaign": "summer_sale",  # Direct UTM on conversion!
                    "utm_source": "google",  # Should take priority!
                },
            )
            flush_persons_and_events_in_batches()

        # Test the attribution priority logic
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="direct_utm_priority",
            conversion_goal_name="Direct UTM Priority",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Validate response structure
        assert response is not None
        assert len(response.results) == 1

        # Important assertion: Direct UTM should win over temporal attribution
        first_result = response.results[0]

        # EXPECTED BEHAVIOR (when properly implemented):
        # Should be summer_sale/google (direct UTM) NOT flash_sale/facebook (temporal)
        assert (
            first_result[0] == "summer_sale"
        ), f"Expected direct UTM 'summer_sale', got '{first_result[0]}'. Direct UTM on conversion event should override temporal attribution!"
        assert (
            first_result[1] == "google"
        ), f"Expected direct UTM 'google', got '{first_result[1]}'. Should NOT use last touchpoint 'facebook'!"

        # Attribution Rule Priority (for implementation):
        # 1. Direct UTM params on conversion event (HIGHEST PRIORITY)
        # 2. Last valid touchpoint before conversion (FALLBACK)
        # 3. Unknown Campaign/Source (DEFAULT)

    def test_temporal_attribution_basic_backward_order(self):
        """
        Test basic temporal attribution when ad comes after conversion.

        Scenario: User converts in April, sees ad in May
        Expected: Conversion should NOT be attributed to the May ad (Unknown attribution)
        Rule: Ads that come after conversions cannot get credit for those conversions
        """
        with freeze_time("2023-04-15"):
            _create_person(distinct_ids=["backward_user"], team=self.team)
            _create_event(
                distinct_id="backward_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 100},  # Conversion with no UTM
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-10"):
            _create_event(
                distinct_id="backward_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "google"},  # Ad after conversion
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="temporal_backward",
            conversion_goal_name="Temporal Backward",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Ad after conversion should NOT attribute
        # Expected: Unknown attribution (not "summer_sale")
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name != "summer_sale", f"Should not attribute to late campaign: {campaign_name}"
        assert campaign_name == "organic", f"Expected organic attribution, got {campaign_name}"
        assert source_name == "organic", f"Expected organic source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_temporal_attribution_multiple_touchpoints_last_touch(self):
        """
        Test Case: Multiple touchpoints before conversion - Last touch attribution

        Scenario: User sees multiple ads before converting, test last-touch attribution
        Timeline:
        - March 10: Email campaign ad (first touch)
        - April 15: Google search ad (last touch before conversion)
        - May 10: Conversion

        Expected: Attribution should go to April Google ad (last touch)
        Note: This tests last-touch attribution model
        """
        with freeze_time("2023-03-10"):
            _create_person(distinct_ids=["multi_touch_user"], team=self.team)
            _create_event(
                distinct_id="multi_touch_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "early_bird", "utm_source": "email"},  # First touch
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-15"):
            _create_event(
                distinct_id="multi_touch_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "spring_sale", "utm_source": "google"},  # Last touch
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-10"):
            _create_event(distinct_id="multi_touch_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multi_touch_last",
            conversion_goal_name="Multi Touch Last",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Last-touch attribution validation
        # Expected: Most recent ad before conversion (April "spring_sale", not March "early_bird")
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "spring_sale", f"Expected last-touch spring_sale, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"
        assert campaign_name != "early_bird", f"Should not attribute to first touch early_bird"

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_temporal_attribution_multiple_touchpoints_first_touch(self):
        """
        Test Case: Multiple touchpoints before conversion - First touch attribution

        Scenario: User sees multiple ads before converting, test first-touch attribution
        Timeline:
        - March 10: Email campaign ad (first touch)
        - April 15: Google search ad (last touch before conversion)
        - May 10: Conversion

        Expected: Attribution should go to March email ad (first touch)
        Note: This tests first-touch attribution model using AttributionModeOperator.FIRST_TOUCH
        """
        with freeze_time("2023-03-10"):
            _create_person(distinct_ids=["first_touch_user"], team=self.team)
            _create_event(
                distinct_id="first_touch_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "early_bird", "utm_source": "email"},  # First touch
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-15"):
            _create_event(
                distinct_id="first_touch_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "spring_sale", "utm_source": "google"},  # Last touch
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-10"):
            _create_event(distinct_id="first_touch_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multi_touch_first",
            conversion_goal_name="Multi Touch First",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        # Create config with first-touch attribution mode
        first_touch_config = MarketingAnalyticsConfig.from_team(self.team)
        first_touch_config.attribution_mode = AttributionMode.FIRST_TOUCH

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=first_touch_config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: First-touch attribution validation
        # Expected: First ad in timeline (March "early_bird", not April "spring_sale")
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "early_bird", f"Expected first-touch early_bird, got {campaign_name}"
        assert source_name == "email", f"Expected email source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"
        assert campaign_name != "spring_sale", f"Should not attribute to last touch spring_sale"
        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    def test_temporal_attribution_touchpoints_before_and_after_conversion(self):
        """
        Test Case: Touchpoints both before AND after conversion

        Scenario: Mixed timeline with ads before and after conversion
        Timeline:
        - March 10: Email ad ✅ (valid - before conversion)
        - April 15: Google ad ✅ (valid - before conversion)
        - May 10: CONVERSION 🎯
        - June 05: Facebook ad ❌ (invalid - after conversion)
        - July 01: Twitter ad ❌ (invalid - after conversion)

        Expected: Only ads before conversion should be considered for attribution
        Attribution should go to April Google ad (last valid touchpoint)
        """
        with freeze_time("2023-03-10"):
            _create_person(distinct_ids=["mixed_timeline_user"], team=self.team)
            _create_event(
                distinct_id="mixed_timeline_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "early_bird", "utm_source": "email"},  # Valid
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-15"):
            _create_event(
                distinct_id="mixed_timeline_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "spring_sale", "utm_source": "google"},  # Valid (last)
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-10"):
            _create_event(
                distinct_id="mixed_timeline_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 100},  # CONVERSION
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-06-05"):
            _create_event(
                distinct_id="mixed_timeline_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "summer_sale", "utm_source": "facebook"},  # Invalid
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-07-01"):
            _create_event(
                distinct_id="mixed_timeline_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "july_promo", "utm_source": "twitter"},  # Invalid
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="mixed_timeline",
            conversion_goal_name="Mixed Timeline",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Should ignore ads after conversion
        # Expected: Attribution to last valid ad before conversion ("spring_sale", not "summer_sale" or "july_promo")
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "spring_sale", f"Expected spring_sale (last valid), got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"
        assert campaign_name != "summer_sale", f"Should ignore ads after conversion"
        assert campaign_name != "july_promo", f"Should ignore ads after conversion"

    def test_temporal_attribution_long_attribution_window(self):
        """
        Test Case: Long attribution window - months apart

        Scenario: User sees ad in January, converts in December (11 months later)
        Timeline:
        - Jan 01: New Year campaign ad
        - Dec 31: Purchase (11 months later)

        Expected: Should attribute if within attribution window
        Tests attribution window limits and long customer journeys
        """
        with freeze_time("2023-01-01"):
            _create_person(distinct_ids=["long_window_user"], team=self.team)
            _create_event(
                distinct_id="long_window_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "new_year", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-12-31"):
            _create_event(
                distinct_id="long_window_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 500},  # High-value conversion after long journey
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="long_window",
            conversion_goal_name="Long Attribution Window",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)
        processor.config.attribution_window_days = 365

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-12-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "new_year", f"Expected new_year campaign, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_temporal_attribution_multiple_conversions_separate_attribution(self):
        """
        Test Case: Multiple conversions with separate attribution tracking

        Scenario: User has multiple conversions, each should be attributed independently
        Timeline:
        - March 10: Spring sale ad
        - April 15: First purchase → should attribute to spring sale
        - May 20: Mother's day ad
        - May 25: Second purchase → should attribute to mother's day
        - June 10: Third purchase → should still attribute to mother's day (no new ads)

        Expected: Each conversion gets attributed to the most recent qualifying ad
        """
        with freeze_time("2023-03-10"):
            _create_person(distinct_ids=["multi_conversion_user"], team=self.team)
            _create_event(
                distinct_id="multi_conversion_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "spring_sale", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-15"):
            _create_event(
                distinct_id="multi_conversion_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 100},  # Conv1 → spring_sale/google
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-20"):
            _create_event(
                distinct_id="multi_conversion_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "mothers_day", "utm_source": "facebook"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-25"):
            _create_event(
                distinct_id="multi_conversion_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 150},  # Conv2 → mothers_day/facebook
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-06-10"):
            _create_event(
                distinct_id="multi_conversion_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 75},  # Conv3 → mothers_day/facebook (still)
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multi_conversion",
            conversion_goal_name="Multi Conversion",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        # Test April conversion attribution (should use spring_sale)
        processor_april = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions_april = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query_april = processor_april.generate_cte_query(additional_conditions_april)
        response_april = execute_hogql_query(query=cte_query_april, team=self.team)

        # With proper temporal attribution, look for the spring_sale attribution result
        assert (
            response_april.results is not None and len(response_april.results) > 0
        ), "Should have attribution results for April"

        # Find the spring_sale attribution (April conversion should be attributed to spring_sale)
        spring_sale_result = None
        for result in response_april.results:
            if result[0] == "spring_sale" and result[1] == "google":
                spring_sale_result = result
                break

        assert (
            spring_sale_result is not None
        ), f"Expected spring_sale attribution for April conversion, got results: {response_april.results}"
        campaign, source, count = spring_sale_result[0], spring_sale_result[1], spring_sale_result[2]
        assert campaign == "spring_sale", f"Expected spring_sale for April purchase, got {campaign}"
        assert source == "google", f"Expected google source for April, got {source}"
        assert count == 1, f"Expected 1 conversion attributed to spring_sale, got {count}"

        # Test May conversion attribution (should use mothers_day)
        processor_may = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions_may = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
        ]

        cte_query_may = processor_may.generate_cte_query(additional_conditions_may)
        response_may = execute_hogql_query(query=cte_query_may, team=self.team)

        # Find the mothers_day attribution (May+ conversions should be attributed to mothers_day)
        assert (
            response_may.results is not None and len(response_may.results) > 0
        ), "Should have attribution results for May"

        mothers_day_result = None
        for result in response_may.results:
            if result[0] == "mothers_day" and result[1] == "meta":
                mothers_day_result = result
                break

        assert (
            mothers_day_result is not None
        ), f"Expected mothers_day attribution for May conversion, got results: {response_may.results}"
        may_campaign, may_source, may_count = mothers_day_result[0], mothers_day_result[1], mothers_day_result[2]
        assert may_campaign == "mothers_day", f"Expected mothers_day for May purchase, got {may_campaign}"
        assert may_source == "meta", f"Expected meta source for May, got {may_source}"
        assert may_count == 2, f"Expected 2 conversions attributed to mothers_day, got {may_count}"

        # Test June conversion attribution (should still use mothers_day - no new ads)
        processor_june = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions_june = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-06-01")]),
            ),
        ]

        cte_query_june = processor_june.generate_cte_query(additional_conditions_june)
        response_june = execute_hogql_query(query=cte_query_june, team=self.team)

        # Find the mothers_day attribution (June conversion should also be attributed to mothers_day)
        assert (
            response_june.results is not None and len(response_june.results) > 0
        ), "Should have attribution results for June"

        june_mothers_day_result = None
        for result in response_june.results:
            if result[0] == "mothers_day" and result[1] == "meta":
                june_mothers_day_result = result
                break

        assert (
            june_mothers_day_result is not None
        ), f"Expected mothers_day attribution for June conversion, got results: {response_june.results}"
        june_campaign, june_source, june_count = (
            june_mothers_day_result[0],
            june_mothers_day_result[1],
            june_mothers_day_result[2],
        )
        assert june_campaign == "mothers_day", f"Expected mothers_day for June purchase, got {june_campaign}"
        assert june_source == "meta", f"Expected meta source for June, got {june_source}"
        assert june_count == 1, f"Expected 1 conversion attributed to mothers_day in June, got {june_count}"

    # ================================================================
    # 11. SAME-DAY TEMPORAL ATTRIBUTION TESTS - Intraday timing precision
    # ================================================================

    def test_temporal_attribution_same_day_morning_evening(self):
        """
        Test Case: Same day temporal order - morning ad, evening conversion

        Scenario: User sees ad in the morning, converts in the evening (same day)
        Timeline:
        - May 15 08:00: Morning email campaign
        - May 15 20:00: Evening purchase

        Expected: Should attribute to morning ad ✅
        Tests intraday temporal precision
        """
        with freeze_time("2023-05-15 08:00:00"):
            _create_person(distinct_ids=["same_day_morning_user"], team=self.team)
            _create_event(
                distinct_id="same_day_morning_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "daily_deal", "utm_source": "email"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-15 20:00:00"):
            _create_event(
                distinct_id="same_day_morning_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="same_day_morning",
            conversion_goal_name="Same Day Morning",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-15")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"
        first_result = response.results[0]

        # Validation: Same-day morning ad → evening conversion
        # Expected: Should attribute to "daily_deal" campaign from morning
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "daily_deal", f"Expected daily_deal campaign, got {campaign_name}"
        assert source_name == "email", f"Expected email source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_temporal_attribution_same_day_evening_morning(self):
        """
        Test Case: Same day temporal order - morning conversion, evening ad

        Scenario: User converts in the morning, sees ad in the evening (same day)
        Timeline:
        - May 15 08:00: Morning purchase
        - May 15 20:00: Evening ad (too late!)

        Expected: Should NOT attribute to evening ad ❌ (Unknown attribution)
        Tests that temporal order matters even within the same day
        """
        with freeze_time("2023-05-15 08:00:00"):
            _create_person(distinct_ids=["same_day_evening_user"], team=self.team)
            _create_event(
                distinct_id="same_day_evening_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-15 20:00:00"):
            _create_event(
                distinct_id="same_day_evening_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "daily_deal", "utm_source": "email"},  # Too late!
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="same_day_evening",
            conversion_goal_name="Same Day Evening",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-15")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Same-day conversion → evening ad should NOT attribute
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name != "daily_deal", f"Should not attribute to late campaign: {campaign_name}"
        assert campaign_name == "organic", f"Expected organic attribution, got {campaign_name}"
        assert source_name == "organic", f"Expected organic source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_temporal_attribution_simultaneous_ad_conversion(self):
        """
        Test Case: Simultaneous ad and conversion at exact same timestamp

        Scenario: Ad view and conversion happen at exactly the same time
        Timeline:
        - May 15 12:00:00.000: Page view with UTM
        - May 15 12:00:00.000: Purchase (exact same timestamp)

        Expected: Should attribute to ad ✅ (ad timestamp <= conversion timestamp)
        Tests edge case of simultaneous events
        """
        timestamp = "2023-05-15 12:00:00"

        with freeze_time(timestamp):
            _create_person(distinct_ids=["simultaneous_user"], team=self.team)
            _create_event(
                distinct_id="simultaneous_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "instant", "utm_source": "google"},
            )
            _create_event(
                distinct_id="simultaneous_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="simultaneous",
            conversion_goal_name="Simultaneous",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-15")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Simultaneous timestamps should attribute
        # Expected: Should attribute to "instant" campaign (ad_timestamp <= conversion_timestamp)
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "instant", f"Expected instant campaign, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_temporal_attribution_one_second_precision(self):
        """
        Test Case: Sub-minute temporal precision - 1 second difference

        Scenario: Conversion happens 1 second before ad view
        Timeline:
        - May 15 12:00:00: Purchase
        - May 15 12:00:01: Ad view (1 second too late)

        Expected: Should NOT attribute ❌ (Unknown attribution)
        Tests temporal precision down to the second level
        """
        with freeze_time("2023-05-15 12:00:00"):
            _create_person(distinct_ids=["one_second_user"], team=self.team)
            _create_event(distinct_id="one_second_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-15 12:00:01"):
            _create_event(
                distinct_id="one_second_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "too_late", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="one_second",
            conversion_goal_name="One Second",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-15")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: 1-second precision should NOT attribute since ad came after conversion
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name != "too_late", f"Should not attribute to late campaign: {campaign_name}"
        assert campaign_name == "organic", f"Expected organic attribution, got {campaign_name}"
        assert source_name == "organic", f"Expected organic source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_temporal_attribution_multiple_conversions_same_campaign(self):
        """
        Test Case: Multiple conversions from the same campaign attribution

        Scenario: User sees one ad campaign, then makes multiple purchases over time
        Timeline:
        - March 01: Spring sale ad campaign
        - April 15: First purchase ✅
        - May 20: Second purchase ✅ (still within attribution window)
        - June 10: Third purchase ✅ (still within attribution window)

        Expected: All 3 conversions should be attributed to the same "spring_sale" campaign
        conversion_count should be 3 (not 1)
        Tests that attribution properly aggregates multiple conversions
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["repeat_buyer"], team=self.team)
            _create_event(
                distinct_id="repeat_buyer",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "spring_sale", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        # First purchase
        with freeze_time("2023-04-15"):
            _create_event(distinct_id="repeat_buyer", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events_in_batches()

        # Second purchase
        with freeze_time("2023-05-20"):
            _create_event(distinct_id="repeat_buyer", event="purchase", team=self.team, properties={"revenue": 75})
            flush_persons_and_events_in_batches()

        # Third purchase
        with freeze_time("2023-06-10"):
            _create_event(distinct_id="repeat_buyer", event="purchase", team=self.team, properties={"revenue": 150})
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multiple_conversions",
            conversion_goal_name="Multiple Conversions",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)
        processor.config.attribution_window_days = 120

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Multiple conversions from same campaign
        # Expected: All 3 purchases should be attributed to "spring_sale" campaign
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "spring_sale", f"Expected spring_sale campaign, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"
        assert conversion_count == 3, f"Expected 3 conversions, got {conversion_count}"

    def test_temporal_attribution_multiple_users_same_campaign(self):
        """
        Test Case: Multiple users converting from the same campaign

        Scenario: Multiple different users see the same ad campaign and convert
        Timeline:
        - April 10: User A sees ad, purchases (1 conversion)
        - April 15: User B sees ad, purchases (1 conversion)
        - April 20: User C sees ad, purchases twice (2 conversions)

        Expected: "spring_sale" campaign should have conversion_count = 4 total
        Tests that attribution properly aggregates conversions across multiple users
        """
        campaign_props = {"utm_campaign": "spring_sale", "utm_source": "google"}

        # User A: sees ad, purchases once
        with freeze_time("2023-04-10"):
            _create_person(distinct_ids=["user_a"], team=self.team)
            _create_event(distinct_id="user_a", event="$pageview", team=self.team, properties=campaign_props)
            _create_event(distinct_id="user_a", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events_in_batches()

        # User B: sees ad, purchases once
        with freeze_time("2023-04-15"):
            _create_person(distinct_ids=["user_b"], team=self.team)
            _create_event(distinct_id="user_b", event="$pageview", team=self.team, properties=campaign_props)
            _create_event(distinct_id="user_b", event="purchase", team=self.team, properties={"revenue": 150})
            flush_persons_and_events_in_batches()

        # User C: sees ad, purchases twice
        with freeze_time("2023-04-20"):
            _create_person(distinct_ids=["user_c"], team=self.team)
            _create_event(distinct_id="user_c", event="$pageview", team=self.team, properties=campaign_props)
            _create_event(distinct_id="user_c", event="purchase", team=self.team, properties={"revenue": 200})
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-21"):
            _create_event(distinct_id="user_c", event="purchase", team=self.team, properties={"revenue": 75})
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multi_user_conversions",
            conversion_goal_name="Multi User Conversions",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Multiple users, multiple conversions aggregation
        # Expected: Total 4 conversions from "spring_sale" campaign across all users
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "spring_sale", f"Expected spring_sale campaign, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"
        assert conversion_count == 4, f"Expected 4 total conversions across users, got {conversion_count}"

    # ================================================================
    # 12. COMPLEX CUSTOMER JOURNEY TESTS - Multi-event, multi-channel attribution
    # ================================================================

    def test_complex_customer_journey_multiple_event_types(self):
        """
        Test Case: Complex customer journey with multiple event types and channels

        Scenario: Full-funnel customer journey across multiple touchpoints and channels
        Timeline:
        - Mar 01: YouTube ad (awareness phase)
        - Mar 15: Email nurture campaign
        - Apr 01: Facebook retargeting ad
        - Apr 05: Add to cart event (intent signal)
        - Apr 10: Purchase (CONVERSION)
        - May 01: Post-purchase upsell email (should not affect purchase attribution)

        Expected: Purchase should be attributed to Facebook retargeting (last paid touchpoint before conversion)
        Post-purchase touchpoints should not affect the original purchase attribution
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["complex_journey_user"], team=self.team)
            _create_event(
                distinct_id="complex_journey_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "awareness", "utm_source": "youtube"},  # Awareness
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-03-15"):
            _create_event(
                distinct_id="complex_journey_user",
                event="email_open",
                team=self.team,
                properties={"utm_campaign": "nurture", "utm_source": "email"},  # Nurturing
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="complex_journey_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "retarget", "utm_source": "facebook"},  # Retargeting
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-05"):
            _create_event(
                distinct_id="complex_journey_user",
                event="add_to_cart",
                team=self.team,
                properties={"utm_campaign": "retarget", "utm_source": "facebook"},  # Intent
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-10"):
            _create_event(
                distinct_id="complex_journey_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 200},  # CONVERSION
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-01"):
            _create_event(
                distinct_id="complex_journey_user",
                event="email_click",
                team=self.team,
                properties={"utm_campaign": "upsell", "utm_source": "email"},  # Post-purchase
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="complex_journey",
            conversion_goal_name="Complex Journey",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Multi-channel last-touch attribution
        # Expected: Should attribute to "retargeting" (last valid touchpoint before conversion)
        # Should ignore "upsell" campaign (came after conversion)
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "retarget", f"Expected retarget (last-touch), got {campaign_name}"
        assert source_name == "meta", f"Expected meta source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"
        assert campaign_name != "upsell", f"Should ignore post-purchase campaigns"

    def test_organic_vs_paid_attribution_organic_then_paid(self):
        """
        Test Case: Organic vs Paid attribution - Organic visit then paid ad

        Scenario: User visits organically first, then through paid ad, then converts
        Timeline:
        - Mar 01: Organic page view (direct visit, no UTM)
        - Apr 01: Paid search ad visit
        - Apr 10: Purchase

        Expected: Attribution should go to paid search (last paid touchpoint)
        Tests how organic vs paid touchpoints are prioritized in attribution
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["organic_paid_user"], team=self.team)
            _create_event(
                distinct_id="organic_paid_user",
                event="$pageview",
                team=self.team,
                properties={},  # Organic - no UTM parameters
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="organic_paid_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "paid_search", "utm_source": "google"},  # Paid
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-10"):
            _create_event(
                distinct_id="organic_paid_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="organic_paid",
            conversion_goal_name="Organic Paid",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Organic → Paid should attribute to paid
        # Expected: Should attribute to "paid_search" (last paid touchpoint)
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "paid_search", f"Expected paid_search campaign, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_organic_vs_paid_attribution_paid_then_organic(self):
        """
        Test Case: Organic vs Paid attribution - Paid ad then organic visit

        Scenario: User visits through paid ad first, then organically, then converts
        Timeline:
        - Mar 01: Paid search ad visit
        - Apr 01: Organic page view (direct visit)
        - Apr 10: Purchase

        Expected: Depends on attribution model:
        - Last-touch: Could be organic or paid (depending on how organic is handled)
        - Paid-only last-touch: Should be paid search (last paid touchpoint)
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["paid_organic_user"], team=self.team)
            _create_event(
                distinct_id="paid_organic_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "paid_search", "utm_source": "google"},  # Paid
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="paid_organic_user",
                event="$pageview",
                team=self.team,
                properties={},  # Organic - no UTM parameters
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-10"):
            _create_event(
                distinct_id="paid_organic_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="paid_organic",
            conversion_goal_name="Paid Organic",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Paid → Organic should attribute to paid
        # Expected: Should attribute to "paid_search" (last paid touchpoint, ignoring organic)
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "paid_search", f"Expected paid_search campaign, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_cross_channel_attribution_full_funnel(self):
        """
        Test Case: Cross-channel attribution across the full marketing funnel

        Scenario: User journey across multiple marketing channels and touchpoints
        Timeline:
        - Week 1: YouTube brand awareness campaign
        - Week 2: Email newsletter click
        - Week 3: Facebook retargeting campaign
        - Week 4: Google search ad (final touchpoint)
        - Week 4: Purchase

        Expected: Attribution should go to Google search ad (last touch)
        Tests multi-channel customer journey attribution
        """
        with freeze_time("2023-03-01"):  # Week 1
            _create_person(distinct_ids=["cross_channel_user"], team=self.team)
            _create_event(
                distinct_id="cross_channel_user",
                event="video_view",
                team=self.team,
                properties={"utm_campaign": "brand_awareness", "utm_source": "youtube"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-03-08"):  # Week 2
            _create_event(
                distinct_id="cross_channel_user",
                event="email_click",
                team=self.team,
                properties={"utm_campaign": "newsletter", "utm_source": "email"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-03-15"):  # Week 3
            _create_event(
                distinct_id="cross_channel_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "retarget", "utm_source": "facebook"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-03-22"):  # Week 4
            _create_event(
                distinct_id="cross_channel_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "search_ad", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-03-24"):  # Week 4
            _create_event(
                distinct_id="cross_channel_user", event="purchase", team=self.team, properties={"revenue": 300}
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="cross_channel",
            conversion_goal_name="Cross Channel",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-03-20")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Multi-channel last-touch attribution
        # Expected: Should attribute to "search_ad" (last touchpoint before conversion)
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "search_ad", f"Expected search_ad (last-touch, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"
        assert campaign_name != "brand_awareness", f"Should not attribute to first touch"

    def test_multi_session_attribution_across_devices(self):
        """
        Test Case: Multi-session attribution across different devices/platforms

        Scenario: User journey spans multiple sessions and potentially different devices
        Timeline:
        - Session 1 (Mobile): Instagram ad, product browsing
        - Session 2 (Desktop): Direct visit, add to cart
        - Session 3 (Mobile): Email reminder, purchase

        Expected: Attribution should go to email campaign (last touchpoint with UTM)
        Tests attribution across session boundaries and device switching
        """
        # Session 1 - Mobile (Instagram discovery)
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["multi_session_user"], team=self.team)
            _create_event(
                distinct_id="multi_session_user",
                event="$pageview",
                team=self.team,
                properties={
                    "utm_campaign": "mobile_ad",
                    "utm_source": "instagram",
                    "$os": "iOS",
                    "$browser": "Mobile Safari",
                },
            )
            _create_event(
                distinct_id="multi_session_user",
                event="product_view",
                team=self.team,
                properties={"utm_campaign": "mobile_ad", "utm_source": "instagram", "$os": "iOS"},
            )
            flush_persons_and_events_in_batches()

        # Session 2 - Desktop (Direct visit)
        with freeze_time("2023-03-15"):
            _create_event(
                distinct_id="multi_session_user",
                event="$pageview",
                team=self.team,
                properties={
                    "$os": "Mac OS X",
                    "$browser": "Chrome",
                    # No UTM - direct visit
                },
            )
            _create_event(
                distinct_id="multi_session_user", event="add_to_cart", team=self.team, properties={"$os": "Mac OS X"}
            )
            flush_persons_and_events_in_batches()

        # Session 3 - Mobile (Email conversion)
        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="multi_session_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "cart_abandonment", "utm_source": "email", "$os": "iOS"},
            )
            _create_event(
                distinct_id="multi_session_user",
                event="purchase",
                team=self.team,
                properties={"revenue": 150, "$os": "iOS"},
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="multi_session",
            conversion_goal_name="Multi Session",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Multi-session cross-device attribution
        # Expected: Should attribute to "cart_abandonment" (last email touchpoint)
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "cart_abandonment", f"Expected cart_abandonment (last-touch), got {campaign_name}"
        assert source_name == "email", f"Expected email source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"
        assert campaign_name != "mobile_ad", f"Should not attribute to first touch"

    # ================================================================
    # 13. ATTRIBUTION WINDOW TESTS - Time-based attribution limits
    # ================================================================

    def test_temporal_attribution_ignores_query_date_range_for_utm_lookback(self):
        """
        Test Case: Temporal attribution should find historical UTM touchpoints outside query range

        Note: Temporal attribution correctly considers ALL historical UTM touchpoints
        for users within the query period, even if those touchpoints occurred before
        the query date range.

        Scenario:
        - March 2023: User sees campaign ad (UTM touchpoint BEFORE query range)
        - May 2023: User converts (within query range)
        - Query Range: May 2023 only (excludes March UTM touchpoint)

        Expected Behavior: Should attribute to March campaign (temporal attribution working)
        Validates: use_temporal_attribution=True ignores query_date_range for UTM lookback
        """
        # Setup: Create UTM touchpoint BEFORE query range
        with freeze_time("2023-03-15"):
            _create_person(distinct_ids=["filtered_utm_user"], team=self.team)
            _create_event(
                distinct_id="filtered_utm_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "early_bird_sale", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        # Setup: Conversion WITHIN query range
        with freeze_time("2023-05-10"):
            _create_event(
                distinct_id="filtered_utm_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="filtered_utm_test",
            conversion_goal_name="Filtered UTM Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        # Note: Query range EXCLUDES the March UTM touchpoint
        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [  # May only!
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.LtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-31")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert response is not None
        assert len(response.results) == 1

        # Validation: Temporal attribution
        # Note: Temporal attribution correctly finds "early_bird_sale" outside query range
        # This proves use_temporal_attribution=True ignores query_date_range for UTM lookback

        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]

        # These assertions validate the CORRECT temporal attribution behavior:
        assert (
            campaign_name == "early_bird_sale"
        ), f"Temporal attribution should find historical campaign outside query range, got {campaign_name}"
        assert (
            source_name == "google"
        ), f"Temporal attribution should find historical source outside query range, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_attribution_window_30_day_limit(self):
        """
        Test Case: 30-day attribution window enforcement

        Scenario: Test conversions within and beyond 30-day attribution window
        Timeline:
        - Day 1: Campaign ad
        - Day 29: Purchase (within 30 days) ✅
        - Day 31: Another purchase (beyond 30 days) ❌

        Expected: First purchase attributed, second purchase not attributed
        Tests attribution window cutoff logic
        """
        with freeze_time("2023-01-01"):
            _create_person(distinct_ids=["window_test_user"], team=self.team)
            _create_event(
                distinct_id="window_test_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "month_start", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-01-29"):  # Day 29 - within window
            _create_event(distinct_id="window_test_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events_in_batches()

        with freeze_time("2023-02-01"):  # Day 31 - beyond window
            _create_event(distinct_id="window_test_user", event="purchase", team=self.team, properties={"revenue": 50})
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="window_30day",
            conversion_goal_name="30 Day Window",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        # Test conversion within 30-day attribution window (should attribute)
        processor_within = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)
        processor_within.config.attribution_window_days = 30

        additional_conditions_within = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-29")]),
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.LtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-31")]),
            ),
        ]

        cte_query_within = processor_within.generate_cte_query(additional_conditions_within)
        response_within = execute_hogql_query(query=cte_query_within, team=self.team)
        assert len(response_within.results) == 1, f"Expected 1 result within window, got {len(response_within.results)}"

        # Validation: Within 30-day window should attribute correctly
        within_result = response_within.results[0]
        within_campaign, within_source, within_count = within_result[0], within_result[1], within_result[2]

        assert within_campaign == "month_start", f"Expected month_start within window, got {within_campaign}"
        assert within_source == "google", f"Expected google source within window, got {within_source}"
        assert within_count == 1, f"Expected 1 conversion within window, got {within_count}"

        # Test conversion beyond 30-day attribution window (should not attribute)
        processor_beyond = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions_beyond = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-02-01")]),
            ),
        ]
        processor_beyond.config.attribution_window_days = 30

        cte_query_beyond = processor_beyond.generate_cte_query(additional_conditions_beyond)
        response_beyond = execute_hogql_query(query=cte_query_beyond, team=self.team)
        assert len(response_beyond.results) == 1, f"Expected 1 result beyond window, got {len(response_beyond.results)}"

        # Validation: Beyond 30-day window should not attribute
        beyond_result = response_beyond.results[0]
        beyond_campaign, beyond_source, beyond_count = beyond_result[0], beyond_result[1], beyond_result[2]

        assert beyond_campaign == "organic", f"Expected organic attribution, got {beyond_campaign}"
        assert beyond_count == 1, f"Expected 1 conversion beyond window, got {beyond_count}"
        assert beyond_source == "organic", f"Expected organic source, got {beyond_source}"

    def test_attribution_window_beyond_limits(self):
        """
        Test Case: Attribution beyond reasonable limits - 2 years

        Scenario: Very old touchpoint should not influence current conversions
        Timeline:
        - Jan 01 2022: Old campaign (2 years ago)
        - Jan 01 2024: Purchase (2 years later)

        Expected: Should not attribute to 2-year-old campaign (Unknown attribution)
        Tests very long attribution window limits

        NOTE: This test expects attribution window limits to be implemented.
        Currently the processor attributes to any campaign regardless of age.
        Business requirement: Implement ~30-90 day attribution window limits.
        """
        with freeze_time("2022-01-01"):
            _create_person(distinct_ids=["old_campaign_user"], team=self.team)
            _create_event(
                distinct_id="old_campaign_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "old_campaign", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2024-01-01"):  # 2 years later
            _create_event(
                distinct_id="old_campaign_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="beyond_limits",
            conversion_goal_name="Beyond Limits",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)
        processor.config.attribution_window_days = 10
        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2022-01-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Should NOT attribute to 2-year-old campaign (beyond attribution window limits)
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name != "old_campaign", f"Should not attribute to 2-year-old campaign: {campaign_name}"
        assert campaign_name == "organic", f"Expected organic attribution, got {campaign_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"
        assert source_name == "organic", f"Expected organic source, got {source_name}"

    # ================================================================
    # 14. DATA QUALITY EDGE CASES - Malformed UTM, duplicates, missing data
    # ================================================================

    def test_malformed_utm_parameters_empty_campaign(self):
        """
        Test Case: Malformed UTM parameters - empty campaign name

        Scenario: UTM parameters with empty or null values
        Timeline:
        - Mar 01: Ad with empty campaign name but valid source
        - Apr 01: Ad with valid campaign but missing source
        - May 01: Ad with missing campaign but valid source
        - Jun 01: Purchase

        Expected: Should handle gracefully with appropriate fallbacks
        Tests data quality handling for incomplete UTM parameters
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["malformed_utm_user"], team=self.team)
            _create_event(
                distinct_id="malformed_utm_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "", "utm_source": "google"},  # Empty campaign
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="malformed_utm_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "valid_campaign"},  # Missing source
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-01"):
            _create_event(
                distinct_id="malformed_utm_user",
                event="$pageview",
                team=self.team,
                properties={"utm_source": "facebook"},  # Missing campaign
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-06-01"):
            _create_event(
                distinct_id="malformed_utm_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="malformed_utm",
            conversion_goal_name="Malformed UTM",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-06-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Should handle malformed UTM gracefully
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        # Should handle gracefully - could attribute to last valid campaign or show Unknown
        assert campaign_name is not None, "Should handle malformed UTM without crashing"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"
        assert source_name == "organic", f"Expected organic source, got {source_name}"

    def test_duplicate_events_same_timestamp_but_first_event_id_is_first(self):
        """
        Test Case: Duplicate events at the same timestamp

        Scenario: Multiple identical or similar events at exact same time
        Timeline:
        - May 15 12:00:00.000: First page view with UTM
        - May 15 12:00:00.000: Duplicate page view with different UTM (same timestamp)
        - May 15 13:00:00.000: Purchase

        Expected: Should handle duplicates appropriately (dedupe or use last processed)
        Tests handling of duplicate/concurrent events
        """
        timestamp = "2023-05-15 12:00:00"

        with freeze_time(timestamp):
            _create_person(distinct_ids=["duplicate_events_user"], team=self.team)
            _create_event(
                distinct_id="duplicate_events_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "duplicate1", "utm_source": "google"},
                event_uuid="11111111-1111-1111-1111-111111111111",
            )
            _create_event(
                distinct_id="duplicate_events_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "duplicate2", "utm_source": "google"},  # Same timestamp
                event_uuid="22222222-2222-2222-2222-222222222222",
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-15 13:00:00"):
            _create_event(
                distinct_id="duplicate_events_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="duplicate_events",
            conversion_goal_name="Duplicate Events",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-15")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Duplicate events handling
        # Expected: Should handle duplicates gracefully (dedupe or use deterministic selection)
        first_result = response.results[0]
        campaign_name, source_name, _conversion_count = first_result[0], first_result[1], first_result[2]
        # Should pick first duplicate campaign deterministically
        assert campaign_name == "duplicate2", f"Expected duplicate2 campaign, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"
        assert _conversion_count == 1, f"Expected 1 conversion, got {_conversion_count}"

    def test_duplicate_events_same_timestamp_but_second_event_id_is_first(self):
        """
        Test Case: Duplicate events at the same timestamp

        Scenario: Multiple identical or similar events at exact same time
        Timeline:
        - May 15 12:00:00.000: First page view with UTM
        - May 15 12:00:00.000: Duplicate page view with different UTM (same timestamp)
        - May 15 13:00:00.000: Purchase

        Expected: Should handle duplicates appropriately (dedupe or use last processed)
        Tests handling of duplicate/concurrent events
        """
        timestamp = "2023-05-15 12:00:00"

        with freeze_time(timestamp):
            _create_person(distinct_ids=["duplicate_events_user"], team=self.team)
            _create_event(
                distinct_id="duplicate_events_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "duplicate1", "utm_source": "google"},
                event_uuid="22222222-2222-2222-2222-222222222222",
            )
            _create_event(
                distinct_id="duplicate_events_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "duplicate2", "utm_source": "google"},  # Same timestamp
                event_uuid="11111111-1111-1111-1111-111111111111",
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-15 13:00:00"):
            _create_event(
                distinct_id="duplicate_events_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="duplicate_events",
            conversion_goal_name="Duplicate Events",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-15")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Duplicate events handling
        # Expected: Should handle duplicates gracefully (dedupe or use deterministic selection)
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        # Should pick first duplicate campaign deterministically
        assert campaign_name == "duplicate1", f"Expected duplicate1 campaign, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_utm_parameters_with_special_characters(self):
        """
        Test Case: UTM parameters containing special characters and encoding

        Scenario: UTM values with special characters, spaces, URL encoding
        Timeline:
        - Mar 01: Ad with special characters in UTM
        - Apr 01: Purchase

        Expected: Should handle special characters properly in attribution
        Tests URL encoding, special characters, and data sanitization
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["special_chars_user"], team=self.team)
            _create_event(
                distinct_id="special_chars_user",
                event="$pageview",
                team=self.team,
                properties={
                    "utm_campaign": "spring sale 2023 - 50% off!",  # Spaces and special chars
                    "utm_source": "google ads & display",  # Ampersand
                    "utm_medium": "cpc/display",  # Forward slash
                    "utm_content": "banner_300x250",  # Underscore
                    "utm_term": "buy now + save",  # Plus sign
                },
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="special_chars_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="special_chars",
            conversion_goal_name="Special Characters",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Special characters handling
        # Expected: Should handle special characters correctly in attribution
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name == "spring sale 2023 - 50% off!", f"Expected special chars campaign, got {campaign_name}"
        assert source_name == "google ads & display", f"Expected special chars source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_very_long_utm_values(self):
        """
        Test Case: Very long UTM parameter values

        Scenario: UTM parameters with extremely long values (potential data quality issue)
        Timeline:
        - Mar 01: Ad with very long UTM values
        - Apr 01: Purchase

        Expected: Should handle long values gracefully (truncate or handle full value)
        Tests handling of abnormally long UTM parameter values
        """
        long_campaign = "very_long_campaign_name_" + "x" * 500
        long_source = "extremely_long_source_name_" + "y" * 300

        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["long_utm_user"], team=self.team)
            _create_event(
                distinct_id="long_utm_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": long_campaign, "utm_source": long_source},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-01"):
            _create_event(distinct_id="long_utm_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="long_utm",
            conversion_goal_name="Long UTM Values",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Very long UTM values handling
        # Expected: Should handle very long values gracefully (truncate or handle full value)
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        assert campaign_name is not None, "Should handle very long UTM values"
        assert source_name is not None, "Should handle very long source values"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_case_sensitivity_utm_parameters(self):
        """
        Test Case: Case sensitivity in UTM parameter values in different time periods

        Scenario: UTM parameters with different case variations
        Timeline:
        - Mar 01: "Google" (capitalized)
        - Mar 15: "google" (lowercase)
        - Apr 01: "GOOGLE" (uppercase)
        - Apr 10: Purchase

        Expected: Should handle case sensitivity consistently
        Tests whether attribution treats "Google", "google", "GOOGLE" as same or different
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["case_sensitive_user"], team=self.team)
            _create_event(
                distinct_id="case_sensitive_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "Spring Sale", "utm_source": "Google"},  # Capitalized
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-03-15"):
            _create_event(
                distinct_id="case_sensitive_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "spring sale", "utm_source": "google"},  # Lowercase
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="case_sensitive_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "SPRING SALE", "utm_source": "GOOGLE"},  # Uppercase
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-10"):
            _create_event(
                distinct_id="case_sensitive_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="case_sensitivity",
            conversion_goal_name="Case Sensitivity",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Case sensitivity handling
        # Expected: Should attribute to last-touch (April "SPRING SALE"/"GOOGLE")
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        # Should use last-touch attribution regardless of case variations
        assert campaign_name == "SPRING SALE", f"Expected SPRING SALE (last-touch), got {campaign_name}"
        assert source_name == "GOOGLE", f"Expected GOOGLE (last-touch, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    def test_null_vs_empty_utm_parameters(self):
        """
        Test Case: Null vs empty string UTM parameters

        Scenario: Different ways UTM parameters can be "missing"
        Timeline:
        - Mar 01: UTM with null values
        - Mar 15: UTM with empty strings
        - Apr 01: UTM completely missing from properties
        - Apr 10: Purchase

        Expected: All should be treated consistently as "Unknown" attribution
        Tests handling of null, empty, and missing UTM parameters
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["null_empty_user"], team=self.team)
            _create_event(
                distinct_id="null_empty_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": None, "utm_source": None},  # Null values
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-03-15"):
            _create_event(
                distinct_id="null_empty_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "", "utm_source": ""},  # Empty strings
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-01"):
            _create_event(
                distinct_id="null_empty_user",
                event="$pageview",
                team=self.team,
                properties={},  # Missing UTM entirely
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-10"):
            _create_event(distinct_id="null_empty_user", event="purchase", team=self.team, properties={"revenue": 100})
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="null_empty",
            conversion_goal_name="Null Empty",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Null vs empty UTM handling
        # Expected: Should show Unknown attribution (all UTM values are null/empty/missing)
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]
        # All touchpoints have null/empty UTM, should show Unknown attribution
        assert campaign_name == "organic", f"Expected organic attribution, got {campaign_name}"
        assert source_name == "organic", f"Expected organic source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

    # ================================================================
    # 15. COMPREHENSIVE INTEGRATION TESTS - Real-world scenarios
    # ================================================================

    def test_non_pageview_utm_parameters_ignored(self):
        """
        Test Case: UTM parameters on non-pageview events should be ignored

        Scenario: User has UTM parameters on various events, but only $pageview events should count
        Timeline:
        - Mar 01: sign_up event with UTM parameters (should be ignored)
        - Mar 05: purchase event with UTM parameters (should be ignored)
        - Mar 10: $pageview event with UTM parameters (should be used for attribution)
        - Apr 01: purchase conversion

        Expected: Attribution should go to the $pageview event UTM, not the other events
        Tests that only $pageview events are considered for UTM attribution
        """
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["non_pageview_user"], team=self.team)
            # Sign-up with UTM - should be ignored
            _create_event(
                distinct_id="non_pageview_user",
                event="sign_up",
                team=self.team,
                properties={"utm_campaign": "ignored_signup", "utm_source": "facebook"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-03-05"):
            # Purchase with UTM - should be ignored
            _create_event(
                distinct_id="non_pageview_user",
                event="purchase",
                team=self.team,
                properties={"utm_campaign": "ignored_purchase", "utm_source": "twitter", "revenue": 50},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-03-10"):
            # $pageview with UTM - should be used for attribution
            _create_event(
                distinct_id="non_pageview_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "valid_pageview", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-01"):
            # Final conversion
            _create_event(
                distinct_id="non_pageview_user", event="purchase", team=self.team, properties={"revenue": 100}
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="non_pageview_utm",
            conversion_goal_name="Non Pageview UTM",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)
        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Only $pageview UTM should be considered
        # Expected: Attribution to "valid_pageview" (NOT "ignored_signup" or "ignored_purchase")
        first_result = response.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]

        # Should attribute to the $pageview event, not the other events with UTM
        assert campaign_name == "valid_pageview", f"Expected attribution to $pageview UTM, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"
        assert campaign_name != "ignored_signup", "Should not attribute to sign_up event UTM"
        assert campaign_name != "ignored_purchase", "Should not attribute to purchase event UTM"

    def test_comprehensive_real_world_attribution_scenario(self):
        """
        Test Case: Comprehensive real-world attribution scenario

        Scenario: Complex, realistic customer journey with multiple edge cases
        Timeline:
        - Week 1: Brand awareness (YouTube) - outside attribution window
        - Week 5: Email campaign (newsletter) - valid touchpoint
        - Week 6: Organic search (no UTM) - between paid touchpoints
        - Week 7: Facebook retargeting - last paid touchpoint
        - Week 7: Purchase with some UTM on conversion event
        - Week 8: Post-purchase upsell (should not affect attribution)
        - Week 10: Second purchase (new attribution cycle)

        Expected: First purchase → Facebook retargeting, Second purchase → Facebook (or Unknown)
        Tests comprehensive real-world attribution complexity
        """
        # Week 1 - Brand awareness (potentially outside window)
        with freeze_time("2023-01-01"):
            _create_person(distinct_ids=["real_world_user"], team=self.team)
            _create_event(
                distinct_id="real_world_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "brand_awareness", "utm_source": "youtube"},
            )
            flush_persons_and_events_in_batches()

        # Week 5 - Email campaign
        with freeze_time("2023-02-01"):
            _create_event(
                distinct_id="real_world_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "newsletter_feb", "utm_source": "email"},
            )
            flush_persons_and_events_in_batches()

        # Week 6 - Organic search (no UTM)
        with freeze_time("2023-02-08"):
            _create_event(
                distinct_id="real_world_user",
                event="$pageview",
                team=self.team,
                properties={},  # Organic - no UTM
            )
            flush_persons_and_events_in_batches()

        # Week 7 - Facebook retargeting (last paid touchpoint)
        with freeze_time("2023-02-15"):
            _create_event(
                distinct_id="real_world_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "retarget_feb", "utm_source": "facebook"},
            )
            flush_persons_and_events_in_batches()

        # Week 7 - First purchase (no UTM on conversion event - tests temporal attribution)
        with freeze_time("2023-02-17"):
            _create_event(
                distinct_id="real_world_user",
                event="purchase",
                team=self.team,
                properties={
                    "revenue": 150,
                    # No UTM on conversion event - should use temporal attribution
                },
            )
            flush_persons_and_events_in_batches()

        # Week 8 - Post-purchase upsell (should not affect first purchase attribution)
        with freeze_time("2023-02-22"):
            _create_event(
                distinct_id="real_world_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "upsell_campaign", "utm_source": "email"},
            )
            flush_persons_and_events_in_batches()

        # Week 10 - Second purchase
        with freeze_time("2023-03-08"):
            _create_event(
                distinct_id="real_world_user",
                event="purchase",
                team=self.team,
                properties={
                    "revenue": 75,  # No UTM on this purchase
                },
            )
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="real_world",
            conversion_goal_name="Real World Scenario",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        # Test first purchase attribution (February 17)
        processor_first = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions_first = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-02-01")]),
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.LtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-02-28")]),
            ),
        ]

        cte_query_first = processor_first.generate_cte_query(additional_conditions_first)
        response_first = execute_hogql_query(query=cte_query_first, team=self.team)

        assert (
            len(response_first.results) == 1
        ), f"Expected 1 result for first purchase, got {len(response_first.results)}"

        # Validation: First purchase should attribute to Facebook retargeting
        # Expected: "retarget_feb"/facebook (ignores post-purchase upsell and partial UTM on conversion)
        first_result = response_first.results[0]
        campaign_name, source_name, conversion_count = first_result[0], first_result[1], first_result[2]

        assert campaign_name == "retarget_feb", f"Expected retarget_feb for first purchase, got {campaign_name}"
        assert source_name == "meta", f"Expected meta source, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion for first purchase, got {conversion_count}"

        # Test both purchases together (full timeline attribution)
        processor_full = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions_full = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-02-01")]),
            ),
        ]

        cte_query_full = processor_full.generate_cte_query(additional_conditions_full)
        response_full = execute_hogql_query(query=cte_query_full, team=self.team)

        # With proper temporal attribution, we should get separate attribution for each conversion
        assert (
            response_full.results is not None and len(response_full.results) > 0
        ), "Should have attribution results for full timeline"

        # Look for both expected attributions: retarget_feb and upsell_campaign
        retarget_result = None
        upsell_result = None

        for result in response_full.results:
            if result[0] == "retarget_feb" and result[1] == "meta":
                retarget_result = result
            elif result[0] == "upsell_campaign" and result[1] == "email":
                upsell_result = result

        # First purchase should be attributed to retarget_feb (Feb 15 ad before Feb 17 purchase)
        assert (
            retarget_result is not None
        ), f"Expected retarget_feb attribution for first purchase, got results: {response_full.results}"
        retarget_campaign, retarget_source, retarget_count = retarget_result[0], retarget_result[1], retarget_result[2]
        assert retarget_campaign == "retarget_feb", f"Expected retarget_feb for first purchase, got {retarget_campaign}"
        assert retarget_source == "meta", f"Expected meta source, got {retarget_source}"
        assert retarget_count == 1, f"Expected 1 conversion attributed to retarget_feb, got {retarget_count}"

        # Second purchase should be attributed to upsell_campaign (Feb 22 ad before Mar 8 purchase)
        assert (
            upsell_result is not None
        ), f"Expected upsell_campaign attribution for second purchase, got results: {response_full.results}"
        upsell_campaign, upsell_source, upsell_count = upsell_result[0], upsell_result[1], upsell_result[2]
        assert (
            upsell_campaign == "upsell_campaign"
        ), f"Expected upsell_campaign for second purchase, got {upsell_campaign}"
        assert upsell_source == "email", f"Expected email source for second purchase, got {upsell_source}"
        assert upsell_count == 1, f"Expected 1 conversion attributed to upsell_campaign, got {upsell_count}"

    def test_cross_device_multi_distinct_id_attribution(self):
        """
        Tests temporal attribution works correctly when user has multiple distinct IDs
        across different devices/sessions (real-world cross-device user journey).
        """

        # Create user journey across multiple distinct IDs
        with freeze_time("2023-03-01"):
            _create_person(distinct_ids=["laptop_anon", "mobile_app", "user@email.com"], team=self.team)
            # UTM campaign from laptop
            _create_event(
                distinct_id="laptop_anon",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "spring_sale", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-03-05"):
            # Mobile browsing (no UTM)
            _create_event(distinct_id="mobile_app", event="$pageview", team=self.team, properties={"page": "/products"})
            flush_persons_and_events_in_batches()

        with freeze_time("2023-03-10"):
            # Purchase from email distinct_id (signed in)
            _create_event(distinct_id="user@email.com", event="purchase", team=self.team, properties={"revenue": 99})
            flush_persons_and_events_in_batches()

        with freeze_time("2023-03-15"):
            # Purchase from original laptop session
            _create_event(distinct_id="laptop_anon", event="purchase", team=self.team, properties={"revenue": 149})
            flush_persons_and_events_in_batches()

        # Test processor handles cross-device attribution correctly
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="cross_device_test",
            conversion_goal_name="Cross Device Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-03-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Should attribute both purchases to spring_sale campaign from laptop
        assert len(response.results) == 1, f"Expected 1 attribution result, got {len(response.results)}"
        campaign, source, conversions = response.results[0][0], response.results[0][1], response.results[0][2]

        assert campaign == "spring_sale", f"Expected spring_sale campaign, got {campaign}"
        assert source == "google", f"Expected google source, got {source}"
        assert conversions == 2, f"Expected 2 conversions (both purchases), got {conversions}"

    def test_cross_session_temporal_attribution_edge_cases(self):
        """
        Tests temporal attribution with complex user journeys across multiple sessions
        and time periods with mixed organic and paid touchpoints.
        """

        # Create complex user journey with multiple distinct IDs over time
        distinct_ids = ["session_1", "session_2", "session_3", "user@test.com", "session_5"]

        with freeze_time("2023-01-15"):
            _create_person(distinct_ids=distinct_ids, team=self.team)
            # First touchpoint: organic
            _create_event(
                distinct_id="session_1",
                event="$pageview",
                team=self.team,
                properties={"$referring_domain": "google.com"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-02-01"):
            # Second session: UTM campaign
            _create_event(
                distinct_id="session_2",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "winter_sale", "utm_source": "facebook"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-02-15"):
            # Third session: different UTM campaign
            _create_event(
                distinct_id="session_3",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "valentines_special", "utm_source": "email"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-03-01"):
            # Fourth session: signed up with email
            _create_event(
                distinct_id="user@test.com", event="sign_up", team=self.team, properties={"source": "website"}
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-03-10"):
            # Purchase 1: Should attribute to valentines_special (most recent UTM)
            _create_event(distinct_id="user@test.com", event="purchase", team=self.team, properties={"revenue": 75})
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-01"):
            # Fifth session: New UTM campaign
            _create_event(
                distinct_id="session_5",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "spring_launch", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-15"):
            # Purchase 2: Should attribute to spring_launch (most recent UTM)
            _create_event(
                distinct_id="session_1",  # Back to original session
                event="purchase",
                team=self.team,
                properties={"revenue": 120},
            )
            flush_persons_and_events_in_batches()

        # Test the complex attribution
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="complex_journey",
            conversion_goal_name="Complex Journey",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-03-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Verify proper temporal attribution across sessions
        results_dict = {}
        for result in response.results:
            key = f"{result[0]}/{result[1]}"
            results_dict[key] = result[2]

        # First purchase (2023-03-10) should use valentines_special (most recent before that date)
        # Second purchase (2023-04-15) should use spring_launch (most recent before that date)
        assert len(results_dict) == 2, f"Expected 2 different attributions, got {len(results_dict)}"

        # Each campaign should get 1 conversion (proper temporal attribution)
        for campaign, conversions in results_dict.items():
            assert conversions == 1, f"Expected 1 conversion per campaign, {campaign} got {conversions}"

        assert "valentines_special/email" in results_dict, "Should have valentines_special attribution"
        assert "spring_launch/google" in results_dict, "Should have spring_launch attribution"

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_attribution_window_sql_structure_demo(self):
        """
        Test Case: Demo of attribution window SQL structure

        Scenario: Test broad attribution window with future dates to demo SQL structure
        Timeline:
        - Jan 01 2025: UTM campaign event
        - Mar 15 2025: Another UTM campaign
        - Jun 06 2025: User conversion (target date)

        Expected: Should generate SQL with attribution window logic
        Attribution window: 6 months (180 days) to include Jan events for Jun conversions
        """
        with freeze_time("2025-01-01"):
            _create_person(distinct_ids=["demo_user"], team=self.team)
            _create_event(
                distinct_id="demo_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "winter_campaign", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2025-03-15"):
            _create_event(
                distinct_id="demo_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "spring_campaign", "utm_source": "facebook"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2025-06-06"):
            _create_event(distinct_id="demo_user", event="user signed up", team=self.team, properties={"value": 1})
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="user signed up",
            conversion_goal_id="demo_signup",
            conversion_goal_name="Demo Signup",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)
        processor.config.attribution_window_days = 180

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2025-06-06")]),
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.LtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2025-07-07")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)

        # This will generate SQL showing our current array-based attribution structure
        # The snapshot will show the actual SQL we generate vs the desired structure
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Should attribute to spring_campaign (most recent before conversion)
        result = response.results[0]
        campaign_name, source_name, conversion_count = result[0], result[1], result[2]
        assert campaign_name == "spring_campaign", f"Expected spring_campaign, got {campaign_name}"
        assert source_name == "meta", f"Expected meta, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_attribution_window_sql_structure_demo_zero_windows(self):
        """
        Test Case: Demo of attribution window SQL structure

        Scenario: Test broad attribution window with future dates to demo SQL structure
        Timeline:
        - Jan 01 2025: UTM campaign event
        - Mar 15 2025: Another UTM campaign
        - Jun 06 2025: User conversion (target date)

        Expected: Should generate SQL with attribution window logic
        Attribution window: 6 months (180 days) to include Jan events for Jun conversions
        """
        with freeze_time("2025-01-01"):
            _create_person(distinct_ids=["demo_user"], team=self.team)
            _create_event(
                distinct_id="demo_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "winter_campaign", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2025-03-15"):
            _create_event(
                distinct_id="demo_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "spring_campaign", "utm_source": "facebook"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2025-06-06"):
            _create_event(distinct_id="demo_user", event="user signed up", team=self.team, properties={"value": 1})
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="user signed up",
            conversion_goal_id="demo_signup",
            conversion_goal_name="Demo Signup",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)
        processor.config.attribution_window_days = 180

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2025-06-06")]),
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.LtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2025-07-07")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)

        # This will generate SQL showing our current array-based attribution structure
        # The snapshot will show the actual SQL we generate vs the desired structure
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Should attribute to spring_campaign (most recent before conversion)
        result = response.results[0]
        campaign_name, source_name, conversion_count = result[0], result[1], result[2]
        assert campaign_name == "spring_campaign", f"Expected spring_campaign, got {campaign_name}"
        assert source_name == "meta", f"Expected meta, got {source_name}"
        assert conversion_count == 1, f"Expected 1 conversion, got {conversion_count}"

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot

    def test_attribution_window_30_day_individual_conversion_boundaries(self):
        """
        Test Case: Attribution window calculated individually per conversion

        Scenario: Two users with different timelines to validate that attribution
        windows are calculated from each conversion date, not the query date range.

        Timeline:
        - May 29 2024: User2 pageview with UTM (social_campaign/facebook)
        - May 30 2024: User1 pageview with UTM (email_campaign/newsletter)
        - June 5 2024: User2 converts (7 days after pageview - within 30-day window)
        - July 1 2024: User1 converts (32 days after pageview - outside 30-day window)

        Query Range: June 2 to July 2 (both conversions included)
        Attribution Window: 30 days

        Expected Results:
        - User1: Should be attributed as "organic" (pageview outside 30-day window)
        - User2: Should be attributed to "social_campaign/facebook" (within window)

        This validates that attribution windows work per-conversion, not per-query.
        """
        # User2: Pageview on May 29 with UTM
        with freeze_time("2024-05-29"):
            _create_person(distinct_ids=["user2"], team=self.team)
            _create_event(
                distinct_id="user2",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "social_campaign", "utm_source": "facebook"},
            )
            flush_persons_and_events_in_batches()

        # User1: Pageview on May 30 with UTM
        with freeze_time("2024-05-30"):
            _create_person(distinct_ids=["user1"], team=self.team)
            _create_event(
                distinct_id="user1",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "email_campaign", "utm_source": "newsletter"},
            )
            flush_persons_and_events_in_batches()

        # User2: Converts on June 5 (7 days after pageview - within 30-day window)
        with freeze_time("2024-06-05"):
            _create_event(distinct_id="user2", event="user signed up", team=self.team, properties={"value": 1})
            flush_persons_and_events_in_batches()

        # User1: Converts on July 1 (32 days after pageview - outside 30-day window)
        with freeze_time("2024-07-01"):
            _create_event(distinct_id="user1", event="user signed up", team=self.team, properties={"value": 1})
            flush_persons_and_events_in_batches()

        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="user signed up",
            conversion_goal_id="signup_goal",
            conversion_goal_name="User Signup",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)
        processor.config.attribution_window_days = 30

        # Query range: June 2 to July 2 (includes both conversions)
        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2024-06-02")]),
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.LtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2024-07-02")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        # Convert results to dict for easier validation
        results_dict = {}
        for result in response.results:
            key = f"{result[0]}/{result[1]}"
            results_dict[key] = result[2]

        # Should have exactly 2 results (one per user)
        assert len(results_dict) == 2, f"Expected 2 results, got {len(results_dict)}: {results_dict}"

        # User2: Within 30-day window - should be attributed to UTM
        assert (
            "social_campaign/meta" in results_dict
        ), f"Missing social_campaign/meta attribution. Results: {results_dict}"
        assert (
            results_dict["social_campaign/meta"] == 1
        ), f"Expected 1 conversion for social_campaign/meta, got {results_dict['social_campaign/meta']}"

        # User1: Outside 30-day window - should be organic
        assert "organic/organic" in results_dict, f"Missing organic attribution. Results: {results_dict}"
        assert (
            results_dict["organic/organic"] == 1
        ), f"Expected 1 conversion for organic, got {results_dict['organic/organic']}"

        # Validate that email_campaign is NOT present (it's outside attribution window)
        assert (
            "email_campaign/newsletter" not in results_dict
        ), f"email_campaign should not be attributed (outside 30-day window). Results: {results_dict}"

    # ================================================================
    # 16. ACTIONS WITH MULTIPLE EVENTS TESTS
    # ================================================================

    def test_actions_multiple_events_simple_count(self):
        """
        Test Case: Action with multiple events - TOTAL math counts all events

        Scenario: Action defined with multiple events, user triggers both
        Timeline:
        - April 10: User sees ad (UTM pageview)
        - April 15: User signs up (event 1 of action)
        - April 20: User activates account (event 2 of action)

        Expected: TOTAL math should count both events (2 conversions)
        """
        with freeze_time("2023-04-10"):
            _create_person(distinct_ids=["multi_event_user"], team=self.team)
            _create_event(
                distinct_id="multi_event_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "conversion_campaign", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-15"):
            _create_event(distinct_id="multi_event_user", event="sign_up", team=self.team)
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-20"):
            _create_event(distinct_id="multi_event_user", event="activate_account", team=self.team)
            flush_persons_and_events_in_batches()

        # Create action with multiple events
        action = Action.objects.create(
            team=self.team, name="User Conversion", steps_json=[{"event": "sign_up"}, {"event": "activate_account"}]
        )

        goal = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id=str(action.id),
            conversion_goal_id="multi_events_total",
            conversion_goal_name="Multi Events Total",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        campaign_name, source_name, conversion_count = response.results[0]

        # Validation: TOTAL should count both events (2 conversions)
        assert conversion_count == 2, f"Expected 2 conversions for TOTAL math, got {conversion_count}"
        assert campaign_name == "conversion_campaign", f"Expected conversion_campaign, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"

    def test_actions_multiple_events_unique_users(self):
        """
        Test Case: Action with multiple events - multiple unique users

        Scenario: Action with multiple events, different users trigger different events
        Timeline:
        - April 10: Ad campaign (all users see it)
        - April 15: User A signs up (event 1)
        - April 20: User B activates account (event 2)
        - April 25: User C signs up (event 1)
        - April 30: User A activates account (event 2)

        Expected: TOTAL = 4 conversions, DAU = 3 unique users
        """
        with freeze_time("2023-04-10"):
            # Create users and show them the ad
            for user_id in ["user_a", "user_b", "user_c"]:
                _create_person(distinct_ids=[user_id], team=self.team)
                _create_event(
                    distinct_id=user_id,
                    event="$pageview",
                    team=self.team,
                    properties={"utm_campaign": "multi_user_campaign", "utm_source": "facebook"},
                )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-15"):
            # User A signs up
            _create_event(
                distinct_id="user_a",
                event="sign_up",
                team=self.team,
                properties={"source": "ad_click"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-20"):
            # User B activates account (without signing up in our data)
            _create_event(
                distinct_id="user_b",
                event="activate_account",
                team=self.team,
                properties={"activation_type": "email_verification"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-25"):
            # User C signs up
            _create_event(
                distinct_id="user_c",
                event="sign_up",
                team=self.team,
                properties={"source": "ad_click"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-30"):
            # User A activates account (second event from same user)
            _create_event(
                distinct_id="user_a",
                event="activate_account",
                team=self.team,
                properties={"activation_type": "email_verification"},
            )
            flush_persons_and_events_in_batches()

        # Create action with multiple events
        action = Action.objects.create(
            team=self.team,
            name="User Conversion Steps",
            steps_json=[{"event": "sign_up"}, {"event": "activate_account"}],
        )

        # Test with TOTAL math
        goal_total = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id=str(action.id),
            conversion_goal_id="multi_users_total",
            conversion_goal_name="Multi Users Total",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor_total = ConversionGoalProcessor(goal=goal_total, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor_total.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert len(response.results) == 1, f"Expected 1 result for TOTAL, got {len(response.results)}"

        # Validation: TOTAL should count all events (4 conversions total)
        campaign_name, source_name, conversion_count = response.results[0]
        assert conversion_count == 4, f"Expected 4 total conversions, got {conversion_count}"

        # Test with DAU math
        goal_dau = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id=str(action.id),
            conversion_goal_id="multi_users_dau",
            conversion_goal_name="Multi Users DAU",
            math=BaseMathType.DAU,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor_dau = ConversionGoalProcessor(goal=goal_dau, index=0, team=self.team, config=self.config)
        cte_query_dau = processor_dau.generate_cte_query(additional_conditions)
        response_dau = execute_hogql_query(query=cte_query_dau, team=self.team)

        assert len(response_dau.results) == 1, f"Expected 1 result for DAU, got {len(response_dau.results)}"

        # Validation: DAU should count unique users (3 unique users)
        campaign_name_dau, source_name_dau, conversion_count_dau = response_dau.results[0]
        assert conversion_count_dau == 3, f"Expected 3 unique users for DAU, got {conversion_count_dau}"

    def test_actions_multiple_events_with_property_filters(self):
        """
        Test Case: Action with multiple events and property filters

        Scenario: Action with multiple events, each with different property filters
        Only events matching the property filters should be counted
        Timeline:
        - April 10: UTM pageview
        - April 15: User signs up with source=ad_click (matches filter) ✅
        - April 20: User activates with activation_type=email (matches filter) ✅
        - April 25: User signs up with source=organic (doesn't match filter) ❌
        - April 30: User activates with activation_type=phone (doesn't match filter) ❌

        Expected: Should only count events that match the property filters (2 conversions)
        """
        with freeze_time("2023-04-10"):
            _create_person(distinct_ids=["filter_user"], team=self.team)
            _create_event(
                distinct_id="filter_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "property_filter_campaign", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-15"):
            # Sign up with matching property
            _create_event(
                distinct_id="filter_user",
                event="sign_up",
                team=self.team,
                properties={"source": "ad_click"},  # This should match
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-20"):
            # Activate with matching property
            _create_event(
                distinct_id="filter_user",
                event="activate_account",
                team=self.team,
                properties={"activation_type": "email_verification"},  # This should match
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-25"):
            # Sign up with non-matching property
            _create_event(
                distinct_id="filter_user",
                event="sign_up",
                team=self.team,
                properties={"source": "organic"},  # This should NOT match
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-30"):
            # Activate with non-matching property
            _create_event(
                distinct_id="filter_user",
                event="activate_account",
                team=self.team,
                properties={"activation_type": "phone_verification"},  # This should NOT match
            )
            flush_persons_and_events_in_batches()

        # Create action with multiple events and property filters
        action = Action.objects.create(
            team=self.team,
            name="Filtered User Conversion",
            steps_json=[
                {"event": "sign_up", "properties": [{"key": "source", "value": "ad_click", "operator": "exact"}]},
                {
                    "event": "activate_account",
                    "properties": [{"key": "activation_type", "value": "email_verification", "operator": "exact"}],
                },
            ],
        )

        goal = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id=str(action.id),
            conversion_goal_id="filtered_multi_events",
            conversion_goal_name="Filtered Multi Events",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        # Validation: Should only count events that match property filters (2 conversions)
        campaign_name, source_name, conversion_count = response.results[0]
        assert conversion_count == 2, f"Expected 2 matching conversions, got {conversion_count}"
        assert campaign_name == "property_filter_campaign", f"Expected property_filter_campaign, got {campaign_name}"
        assert source_name == "google", f"Expected google source, got {source_name}"

    def test_actions_multiple_events_and_vs_or_semantics(self):
        """
        Test Case: Understanding AND vs OR semantics for actions with multiple events

        Question: If an action has 2 events, and a user triggers both, is that:
        - 1 conversion (AND logic - both events needed for 1 conversion)
        - 2 conversions (OR logic - each event is a separate conversion)

        This test clarifies the current behavior.
        """
        with freeze_time("2023-04-10"):
            _create_person(distinct_ids=["semantics_user"], team=self.team)
            _create_event(
                distinct_id="semantics_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "test_campaign", "utm_source": "google"},
            )
            flush_persons_and_events_in_batches()

        # User triggers ONLY the first event
        with freeze_time("2023-04-15"):
            _create_event(
                distinct_id="semantics_user",
                event="sign_up",
                team=self.team,
            )
            flush_persons_and_events_in_batches()

        # Create action with 2 events
        action_both_events = Action.objects.create(
            team=self.team, name="Two Event Action", steps_json=[{"event": "sign_up"}, {"event": "activate_account"}]
        )

        goal = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id=str(action_both_events.id),
            conversion_goal_id="semantics_test",
            conversion_goal_name="Semantics Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        # Test with only first event triggered
        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        first_event_only_count = response.results[0][2] if response.results else 0

        # Now user triggers the second event too
        with freeze_time("2023-04-20"):
            _create_event(distinct_id="semantics_user", event="activate_account", team=self.team)
            flush_persons_and_events_in_batches()

        # Test again with both events triggered
        response_both = execute_hogql_query(query=cte_query, team=self.team)
        both_events_count = response_both.results[0][2] if response_both.results else 0

        # Validation: Multi-event actions use OR logic - each matching event is a separate conversion
        assert first_event_only_count == 1, f"Expected 1 conversion after first event, got {first_event_only_count}"
        assert both_events_count == 2, f"Expected 2 conversions (OR logic), got {both_events_count}"

    def test_action_attribution_behavior_detailed(self):
        """
        Test Case: Actions with temporal attribution correctly attribute to prior UTM pageviews

        Scenario: UTM pageview → action event
        Expected: Action should attribute to the prior pageview UTM parameters
        """
        with freeze_time("2023-04-10"):
            _create_person(distinct_ids=["attribution_test_user"], team=self.team)
            _create_event(
                distinct_id="attribution_test_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "paid_campaign", "utm_source": "google_ads"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-04-15"):
            _create_event(distinct_id="attribution_test_user", event="sign_up", team=self.team)
            flush_persons_and_events_in_batches()

        action = Action.objects.create(team=self.team, name="Sign Up Action", steps_json=[{"event": "sign_up"}])

        goal = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id=str(action.id),
            conversion_goal_id="attribution_test",
            conversion_goal_name="Attribution Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)
        additional_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-04-01")]),
            ),
        ]

        cte_query = processor.generate_cte_query(additional_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert len(response.results) == 1, f"Expected 1 result, got {len(response.results)}"

        campaign, source, count = response.results[0]
        assert campaign == "paid_campaign", f"Expected paid_campaign, got {campaign}"
        assert source == "google_ads", f"Expected google_ads, got {source}"
        assert count == 1, f"Expected 1 conversion, got {count}"

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_integration_multi_event_actions_temporal_attribution(self):
        """
        Integration test: Multi-event ActionsNode temporal attribution vs EventsNode

        Validates:
        - Multi-event actions correctly attribute to prior pageview UTMs
        - ActionsNode vs EventsNode SQL generation differences
        - OR logic for actions containing multiple events

        Scenario: UTM pageview → sign_up event → activate_account event
        Expected: Both action events attribute to same pageview UTMs
        """
        # Create test data with temporal attribution scenario
        with freeze_time("2023-06-01 10:00:00"):
            _create_person(distinct_ids=["test_user"], team=self.team)
            _create_event(
                distinct_id="test_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "summer_launch", "utm_source": "twitter_ads"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-06-01 10:05:00"):
            _create_event(distinct_id="test_user", event="sign_up", team=self.team)
            flush_persons_and_events_in_batches()

        with freeze_time("2023-06-01 10:10:00"):
            _create_event(distinct_id="test_user", event="activate_account", team=self.team)
            flush_persons_and_events_in_batches()

        # Create multi-event action
        action = Action.objects.create(
            team=self.team, name="User Onboarding", steps_json=[{"event": "sign_up"}, {"event": "activate_account"}]
        )

        # Configure processors for comparison
        schema_map = {"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"}

        events_goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="sign_up",
            conversion_goal_id="events_test",
            conversion_goal_name="Events Test",
            math=BaseMathType.TOTAL,
            schema_map=schema_map,
        )

        actions_goal = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id=str(action.id),
            conversion_goal_id="actions_test",
            conversion_goal_name="Actions Test",
            math=BaseMathType.TOTAL,
            schema_map=schema_map,
        )

        date_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-06-01")]),
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.LtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-06-02")]),
            ),
        ]

        # Execute queries
        events_processor = ConversionGoalProcessor(goal=events_goal, index=0, team=self.team, config=self.config)
        actions_processor = ConversionGoalProcessor(goal=actions_goal, index=1, team=self.team, config=self.config)

        events_query = events_processor.generate_cte_query(date_conditions)
        actions_query = actions_processor.generate_cte_query(date_conditions)

        events_response = execute_hogql_query(query=events_query, team=self.team)
        actions_response = execute_hogql_query(query=actions_query, team=self.team)

        # Validate attribution results
        assert len(events_response.results) == 1
        assert len(actions_response.results) == 1

        events_campaign, events_source, events_count = events_response.results[0]
        actions_campaign, actions_source, actions_count = actions_response.results[0]

        # Both should attribute to same UTM source
        assert events_campaign == actions_campaign == "summer_launch"
        assert events_source == actions_source == "twitter_ads"

        # ActionsNode should count both events, EventsNode only one
        assert events_count == 1
        assert actions_count == 2

        assert pretty_print_in_tests(actions_response.hogql, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_integration_actions_node_temporal_attribution_sql_validation(self):
        """
        Integration test: ActionsNode temporal attribution with SQL structure validation

        Validates:
        - End-to-end ActionsNode temporal attribution functionality
        - Correct SQL generation with OR logic for temporal UTM lookup
        - Action condition distribution across array collection queries

        Scenario: UTM pageview → action event
        Expected: Action correctly attributes to prior pageview UTMs
        """
        # Create temporal attribution test data
        with freeze_time("2023-05-01"):
            _create_person(distinct_ids=["test_user"], team=self.team)
            _create_event(
                distinct_id="test_user",
                event="$pageview",
                team=self.team,
                properties={"utm_campaign": "spring_campaign", "utm_source": "facebook"},
            )
            flush_persons_and_events_in_batches()

        with freeze_time("2023-05-02"):
            _create_event(distinct_id="test_user", event="sign_up", team=self.team)
            flush_persons_and_events_in_batches()

        # Create action and processor
        action = _create_action(team=self.team, name="User Signup Action", event_name="sign_up")

        goal = ConversionGoalFilter2(
            kind=NodeKind.ACTIONS_NODE,
            id=str(action.id),
            conversion_goal_id="signup_test",
            conversion_goal_name="Signup Test",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

        processor = ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=self.config)

        date_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-01")]),
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.LtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-05-03")]),
            ),
        ]

        # Execute query and validate attribution results
        cte_query = processor.generate_cte_query(date_conditions)
        response = execute_hogql_query(query=cte_query, team=self.team)

        assert len(response.results) == 1
        campaign_name, source_name, conversion_count = response.results[0]

        assert campaign_name == "spring_campaign"
        assert source_name == "meta"
        assert conversion_count == 1

        assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot
