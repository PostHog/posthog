"""Tests for experiment metric utilities."""

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.actions.backend.models.action import Action
from products.experiments.backend.metric_utils import (
    collect_metric_events_and_action_ids,
    collect_metric_warehouse_tables,
    refresh_action_names_in_metric,
    resolve_action_events,
)


class TestRefreshActionNamesInMetric(BaseTest):
    """Test that action names are refreshed in experiment metrics."""

    def setUp(self):
        super().setUp()
        # Create test actions
        self.action1 = Action.objects.create(team=self.team, name="Original Action 1")
        self.action2 = Action.objects.create(team=self.team, name="Original Action 2")
        self.action3 = Action.objects.create(team=self.team, name="Original Action 3")

    def test_refresh_action_names_in_mean_metric(self):
        """Test refreshing action names in a mean metric."""
        query = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {
                "kind": "ActionsNode",
                "id": self.action1.id,
                "name": "Original Action 1",
            },
        }

        # Rename the action
        self.action1.name = "Renamed Action 1"
        self.action1.save()

        # Refresh action names
        updated_query = refresh_action_names_in_metric(query, self.team)

        # Verify the name was updated
        assert updated_query is not None
        assert updated_query["source"]["name"] == "Renamed Action 1"
        assert updated_query["source"]["id"] == self.action1.id
        assert updated_query["source"]["kind"] == "ActionsNode"

    def test_refresh_action_names_in_funnel_metric(self):
        """Test refreshing action names in a funnel metric with multiple steps."""
        query = {
            "kind": "ExperimentMetric",
            "metric_type": "funnel",
            "series": [
                {
                    "kind": "ActionsNode",
                    "id": self.action1.id,
                    "name": "Original Action 1",
                },
                {
                    "kind": "EventsNode",
                    "event": "pageview",
                    "name": "Pageview",
                },
                {
                    "kind": "ActionsNode",
                    "id": self.action2.id,
                    "name": "Original Action 2",
                },
            ],
        }

        # Rename both actions
        self.action1.name = "Renamed Action 1"
        self.action1.save()
        self.action2.name = "Renamed Action 2"
        self.action2.save()

        # Refresh action names
        updated_query = refresh_action_names_in_metric(query, self.team)

        # Verify action names were updated but event name was not changed
        assert updated_query is not None
        assert updated_query["series"][0]["name"] == "Renamed Action 1"
        assert updated_query["series"][1]["name"] == "Pageview"  # EventsNode unchanged
        assert updated_query["series"][2]["name"] == "Renamed Action 2"

    @parameterized.expand(
        [
            ("ratio", "numerator", "denominator"),
            ("retention", "start_event", "completion_event"),
        ]
    )
    def test_refresh_action_names_in_dual_field_metric(self, metric_type: str, field1: str, field2: str):
        """Test refreshing action names in metrics with two ActionsNode fields."""
        query = {
            "kind": "ExperimentMetric",
            "metric_type": metric_type,
            field1: {
                "kind": "ActionsNode",
                "id": self.action1.id,
                "name": "Original Action 1",
            },
            field2: {
                "kind": "ActionsNode",
                "id": self.action2.id,
                "name": "Original Action 2",
            },
        }

        # Rename the actions
        self.action1.name = "Renamed Action 1"
        self.action1.save()
        self.action2.name = "Renamed Action 2"
        self.action2.save()

        # Refresh action names
        updated_query = refresh_action_names_in_metric(query, self.team)

        # Verify both names were updated
        assert updated_query is not None
        assert updated_query[field1]["name"] == "Renamed Action 1"
        assert updated_query[field2]["name"] == "Renamed Action 2"

    def test_does_not_modify_events_node(self):
        """Test that EventsNode names are not modified."""
        query = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {
                "kind": "EventsNode",
                "event": "pageview",
                "name": "Custom Pageview Name",
            },
        }

        # Refresh action names
        updated_query = refresh_action_names_in_metric(query, self.team)

        # Verify EventsNode name was not changed
        assert updated_query is not None
        assert updated_query["source"]["name"] == "Custom Pageview Name"

    @parameterized.expand(
        [
            ("missing", False),
            ("deleted", True),
        ]
    )
    def test_handles_nonexistent_action(self, scenario: str, action_exists: bool):
        """Test that missing or deleted actions don't cause errors."""
        if action_exists:
            action_id = self.action1.id
            self.action1.deleted = True
            self.action1.save()
        else:
            action_id = 99999

        query = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {
                "kind": "ActionsNode",
                "id": action_id,
                "name": "Original Name",
            },
        }

        # Refresh action names (should not crash)
        updated_query = refresh_action_names_in_metric(query, self.team)

        # Verify the name remains unchanged when action doesn't exist
        assert updated_query is not None
        assert updated_query["source"]["name"] == "Original Name"

    @parameterized.expand(
        [
            # Legacy query format
            (
                "legacy",
                {
                    "kind": "ExperimentTrendsQuery",
                    "series": [{"kind": "ActionsNode", "id": 1, "name": "Old Name"}],
                },
            ),
            # Empty query
            ("empty", {}),
            # None
            ("none", None),
        ]
    )
    def test_non_experiment_metric_query_unchanged(self, _name: str, query: dict | None):
        """Test that non-ExperimentMetric queries are returned unchanged."""
        updated_query = refresh_action_names_in_metric(query, self.team)
        assert updated_query == query

    def test_query_not_mutated(self):
        """Test that the original query is not mutated."""
        from typing import Any

        original_query: dict[str, Any] = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {
                "kind": "ActionsNode",
                "id": self.action1.id,
                "name": "Original Action 1",
            },
        }

        # Rename the action
        self.action1.name = "Renamed Action 1"
        self.action1.save()

        # Store original name
        original_name = original_query["source"]["name"]

        # Refresh action names
        updated_query = refresh_action_names_in_metric(original_query, self.team)

        # Verify original query was not mutated
        assert original_query["source"]["name"] == original_name
        assert updated_query is not None
        assert isinstance(updated_query, dict)
        assert updated_query["source"]["name"] == "Renamed Action 1"

    def test_handles_nested_structures(self):
        """Test that deeply nested ActionsNode structures are handled."""
        query = {
            "kind": "ExperimentMetric",
            "metric_type": "funnel",
            "series": [
                {
                    "kind": "ActionsNode",
                    "id": self.action1.id,
                    "name": "Original Action 1",
                    "properties": [
                        {
                            "type": "event",
                            "key": "some_property",
                        }
                    ],
                }
            ],
            "breakdownFilter": {
                "breakdown": "country",
            },
        }

        # Rename the action
        self.action1.name = "Renamed Action 1"
        self.action1.save()

        # Refresh action names
        updated_query = refresh_action_names_in_metric(query, self.team)

        # Verify the action name was updated
        assert updated_query is not None
        assert isinstance(updated_query, dict)
        assert updated_query["series"][0]["name"] == "Renamed Action 1"
        # Verify other properties remain intact
        assert updated_query["series"][0]["properties"][0]["key"] == "some_property"
        assert updated_query["breakdownFilter"]["breakdown"] == "country"

    def test_batch_fetching_actions(self):
        """Test that multiple actions are fetched in a single query."""
        query = {
            "kind": "ExperimentMetric",
            "metric_type": "funnel",
            "series": [
                {"kind": "ActionsNode", "id": self.action1.id, "name": "Original Action 1"},
                {"kind": "ActionsNode", "id": self.action2.id, "name": "Original Action 2"},
                {"kind": "ActionsNode", "id": self.action3.id, "name": "Original Action 3"},
            ],
        }

        # Rename all actions
        self.action1.name = "Renamed Action 1"
        self.action1.save()
        self.action2.name = "Renamed Action 2"
        self.action2.save()
        self.action3.name = "Renamed Action 3"
        self.action3.save()

        # Count queries executed
        with self.assertNumQueries(1):  # Should be a single query to fetch all actions
            updated_query = refresh_action_names_in_metric(query, self.team)

        # Verify all names were updated
        assert updated_query is not None
        assert updated_query["series"][0]["name"] == "Renamed Action 1"
        assert updated_query["series"][1]["name"] == "Renamed Action 2"
        assert updated_query["series"][2]["name"] == "Renamed Action 3"


class TestCollectMetricEventsAndActionIds(BaseTest):
    @parameterized.expand(
        [
            (
                "mean",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "purchase"},
                },
                {"purchase"},
            ),
            (
                "funnel",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "funnel",
                    "series": [
                        {"kind": "EventsNode", "event": "signup"},
                        {"kind": "EventsNode", "event": "activated"},
                    ],
                },
                {"signup", "activated"},
            ),
            (
                "ratio",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "ratio",
                    "numerator": {"kind": "EventsNode", "event": "revenue"},
                    "denominator": {"kind": "EventsNode", "event": "$pageview"},
                },
                {"revenue", "$pageview"},
            ),
            (
                "retention",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "retention",
                    "start_event": {"kind": "EventsNode", "event": "first_open"},
                    "completion_event": {"kind": "EventsNode", "event": "returned"},
                },
                {"first_open", "returned"},
            ),
        ]
    )
    def test_extracts_events_from_metric_type(self, _name: str, metric: dict, expected: set[str]):
        events, action_ids = collect_metric_events_and_action_ids([metric])
        assert events == expected
        assert action_ids == set()

    def test_ignores_null_event_meaning_all_events(self):
        metric = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {"kind": "EventsNode", "event": None},
        }
        events, action_ids = collect_metric_events_and_action_ids([metric])
        assert events == set()
        assert action_ids == set()

    def test_collects_action_ids_without_resolving(self):
        metric = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {"kind": "ActionsNode", "id": 7},
        }
        events, action_ids = collect_metric_events_and_action_ids([metric])
        assert events == set()
        assert action_ids == {7}

    def test_combines_events_across_multiple_metrics(self):
        metrics = [
            {"kind": "ExperimentMetric", "metric_type": "mean", "source": {"kind": "EventsNode", "event": "a"}},
            {"kind": "ExperimentMetric", "metric_type": "mean", "source": {"kind": "EventsNode", "event": "b"}},
        ]
        events, _ = collect_metric_events_and_action_ids(metrics)
        assert events == {"a", "b"}

    def test_empty_metrics_returns_empty_sets(self):
        assert collect_metric_events_and_action_ids([]) == (set(), set())

    def test_collect_does_not_touch_the_db(self):
        metrics = [
            {"kind": "ExperimentMetric", "metric_type": "mean", "source": {"kind": "EventsNode", "event": "purchase"}},
            {"kind": "ExperimentMetric", "metric_type": "mean", "source": {"kind": "ActionsNode", "id": 7}},
        ]
        with self.assertNumQueries(0):
            events, action_ids = collect_metric_events_and_action_ids(metrics)
        assert events == {"purchase"}
        assert action_ids == {7}


class TestCollectMetricWarehouseTables(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "mean",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "ExperimentDataWarehouseNode", "table_name": "stripe_charges"},
                },
                {"stripe_charges"},
            ),
            (
                "funnel",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "funnel",
                    "series": [
                        {"kind": "EventsNode", "event": "signup"},
                        {"kind": "ExperimentDataWarehouseNode", "table_name": "orders"},
                    ],
                },
                {"orders"},
            ),
            (
                "ratio",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "ratio",
                    "numerator": {"kind": "ExperimentDataWarehouseNode", "table_name": "revenue"},
                    "denominator": {"kind": "EventsNode", "event": "$pageview"},
                },
                {"revenue"},
            ),
            (
                "retention",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "retention",
                    "start_event": {"kind": "ExperimentDataWarehouseNode", "table_name": "trials"},
                    "completion_event": {"kind": "ExperimentDataWarehouseNode", "table_name": "subscriptions"},
                },
                {"trials", "subscriptions"},
            ),
        ]
    )
    def test_collects_table_names_by_metric_type(self, _name: str, metric: dict, expected: set[str]):
        assert collect_metric_warehouse_tables([metric]) == expected

    def test_ignores_event_and_action_nodes(self):
        metric = {
            "kind": "ExperimentMetric",
            "metric_type": "funnel",
            "series": [{"kind": "EventsNode", "event": "x"}, {"kind": "ActionsNode", "id": 1}],
        }
        assert collect_metric_warehouse_tables([metric]) == set()

    def test_ignores_warehouse_node_without_table_name(self):
        metric = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {"kind": "ExperimentDataWarehouseNode", "table_name": ""},
        }
        assert collect_metric_warehouse_tables([metric]) == set()

    def test_combines_tables_across_metrics(self):
        # SimpleTestCase forbids DB access, so this also locks in that collection touches no DB.
        metrics = [
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "ExperimentDataWarehouseNode", "table_name": "a"},
            },
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "ExperimentDataWarehouseNode", "table_name": "b"},
            },
        ]
        assert collect_metric_warehouse_tables(metrics) == {"a", "b"}

    def test_empty_metrics_returns_empty_set(self):
        assert collect_metric_warehouse_tables([]) == set()


class TestResolveActionEvents(BaseTest):
    def test_resolves_actions_to_their_step_events(self):
        action = Action.objects.create(
            team=self.team,
            name="Signed up",
            steps_json=[{"event": "signup"}, {"event": "$autocapture"}],
        )
        assert resolve_action_events({action.id}, self.team) == {action.id: {"signup", "$autocapture"}}

    def test_ignores_deleted_actions(self):
        action = Action.objects.create(team=self.team, name="Gone", steps_json=[{"event": "ghost"}], deleted=True)
        assert resolve_action_events({action.id}, self.team) == {}

    def test_batches_into_single_query(self):
        action_a = Action.objects.create(team=self.team, name="A", steps_json=[{"event": "a1"}, {"event": "a2"}])
        action_b = Action.objects.create(team=self.team, name="B", steps_json=[{"event": "b1"}])

        with self.assertNumQueries(1):
            resolved = resolve_action_events({action_a.id, action_b.id}, self.team)

        assert resolved == {action_a.id: {"a1", "a2"}, action_b.id: {"b1"}}

    def test_empty_makes_no_query(self):
        with self.assertNumQueries(0):
            assert resolve_action_events(set(), self.team) == {}
