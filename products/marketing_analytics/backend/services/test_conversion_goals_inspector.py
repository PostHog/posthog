from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from posthog.schema import DateRange

from products.actions.backend.models.action import Action
from products.marketing_analytics.backend.services.conversion_goals_inspector import (
    explain_conversion_goal,
    list_conversion_goals,
)


def _events_goal(goal_id: str = "purchase", event: str | None = "purchase"):
    return {
        "conversion_goal_id": goal_id,
        "conversion_goal_name": goal_id,
        "kind": "EventsNode",
        "event": event,
        "schema_map": {},
    }


def _actions_goal(goal_id: str = "42"):
    return {
        "conversion_goal_id": goal_id,
        "conversion_goal_name": "Sign up action",
        "kind": "ActionsNode",
        "schema_map": {},
    }


def _dw_goal(goal_id: str = "stripe_charges", table_name: str = "stripe.charges"):
    return {
        "conversion_goal_id": goal_id,
        "conversion_goal_name": "Stripe charges",
        "kind": "DataWarehouseNode",
        "table_name": table_name,
        "id_field": "id",
        "distinct_id_field": "customer_email",
        "timestamp_field": "created_at",
        "schema_map": {},
    }


class _InspectorMixin(APIBaseTest):
    """Shared setUp that patches all DB helpers used by list/explain conversion goals."""

    def setUp(self):
        super().setUp()
        from products.marketing_analytics.backend.services.native_integrations import canonical_source_aliases

        _targets = {
            "config": "products.marketing_analytics.backend.services.conversion_goals_inspector._read_team_goal_config",
            "alias_map": "products.marketing_analytics.backend.services.conversion_goals_inspector._build_team_alias_map",
            "event_count": "products.marketing_analytics.backend.services.conversion_goals_inspector._count_event_goal",
            "action_count": "products.marketing_analytics.backend.services.conversion_goals_inspector._count_action_goal",
            "dw_count": "products.marketing_analytics.backend.services.conversion_goals_inspector._count_dw_goal",
            "resolve_action": "products.marketing_analytics.backend.services.conversion_goals_inspector._resolve_action",
        }
        self.mocks: dict[str, AsyncMock] = {}
        for key, target in _targets.items():
            p = patch(target, new_callable=AsyncMock)
            self.mocks[key] = p.start()
            self.addCleanup(p.stop)

        self.mocks["config"].return_value = ([], 90, "last_touch")
        self.mocks["alias_map"].return_value = dict(canonical_source_aliases())
        self.mocks["event_count"].return_value = (0, 0, 0, 0)
        self.mocks["action_count"].return_value = (0, 0, 0, 0)
        self.mocks["dw_count"].return_value = (0, None)
        self.mocks["resolve_action"].return_value = (None, None)


class TestListConversionGoals(_InspectorMixin):
    @pytest.mark.asyncio
    async def test_no_goals_returns_empty(self):
        response = await list_conversion_goals(self.team)
        assert response.goals == []
        assert response.has_misconfigured is False
        assert response.attribution_window_days == 90

    @pytest.mark.asyncio
    async def test_events_node_goal_summarized_with_split(self):
        self.mocks["config"].return_value = ([_events_goal("purchase")], 60, "first_touch")
        # 200 total: 80 integrated, 70 events without utm_source, 50 with unmatched utm_source
        self.mocks["event_count"].return_value = (200, 80, 70, 50)

        response = await list_conversion_goals(self.team)

        assert response.attribution_window_days == 60
        assert response.attribution_mode == "first_touch"
        assert len(response.goals) == 1
        goal = response.goals[0]
        assert goal.id == "purchase"
        assert goal.kind == "EventsNode"
        assert goal.target_label == "purchase"
        assert goal.last_30d_count == 200
        assert goal.integrated_count == 80
        assert goal.events_without_utm_source == 70
        assert goal.events_with_unmatched_utm_source == 50
        assert goal.non_integrated_count == 120
        assert goal.integrated_pct == 40.0
        assert goal.is_misconfigured is False

    @pytest.mark.asyncio
    async def test_events_node_with_null_event_uses_all_events_label(self):
        self.mocks["config"].return_value = ([_events_goal("any", event=None)], 90, "last_touch")
        self.mocks["event_count"].return_value = (10, 0, 10, 0)

        response = await list_conversion_goals(self.team)
        assert response.goals[0].target_label == "(all events)"
        assert response.goals[0].events_without_utm_source == 10
        assert response.goals[0].events_with_unmatched_utm_source == 0

    @pytest.mark.asyncio
    async def test_actions_node_with_missing_action_marks_misconfigured(self):
        self.mocks["config"].return_value = ([_actions_goal("999")], 90, "last_touch")
        self.mocks["resolve_action"].return_value = (None, "Action 999 does not exist or is deleted")

        response = await list_conversion_goals(self.team)
        assert response.has_misconfigured is True
        assert response.goals[0].is_misconfigured is True
        assert "999" in (response.goals[0].misconfig_reason or "")

    @pytest.mark.asyncio
    async def test_actions_node_with_resolved_action_uses_action_name(self):
        action_mock = MagicMock()
        action_mock.name = "Sign up"
        self.mocks["config"].return_value = ([_actions_goal("42")], 90, "last_touch")
        self.mocks["resolve_action"].return_value = (action_mock, None)
        # 50 total: 30 integrated, 12 without utm_source, 8 with unmatched utm_source.
        self.mocks["action_count"].return_value = (50, 30, 12, 8)

        response = await list_conversion_goals(self.team)
        goal = response.goals[0]
        assert goal.kind == "ActionsNode"
        assert goal.target_label == "Action: Sign up"
        assert goal.last_30d_count == 50
        assert goal.integrated_count == 30
        assert goal.events_without_utm_source == 12
        assert goal.events_with_unmatched_utm_source == 8
        assert goal.non_integrated_count == 20
        assert goal.is_misconfigured is False

    @pytest.mark.asyncio
    async def test_data_warehouse_node_returns_count_without_split(self):
        self.mocks["config"].return_value = ([_dw_goal()], 90, "last_touch")
        self.mocks["dw_count"].return_value = (1500, None)

        response = await list_conversion_goals(self.team)
        goal = response.goals[0]
        assert goal.kind == "DataWarehouseNode"
        assert goal.target_label == "stripe.charges"
        assert goal.last_30d_count == 1500
        assert goal.integrated_count is None
        assert goal.events_without_utm_source is None
        assert goal.events_with_unmatched_utm_source is None
        assert goal.non_integrated_count is None
        assert goal.integrated_pct is None
        assert goal.is_misconfigured is False

    @pytest.mark.asyncio
    async def test_data_warehouse_node_with_query_error_marks_misconfigured(self):
        self.mocks["config"].return_value = ([_dw_goal()], 90, "last_touch")
        self.mocks["dw_count"].return_value = (0, "DW table or column not queryable: relation does not exist")

        response = await list_conversion_goals(self.team)
        assert response.goals[0].is_misconfigured is True
        assert "not queryable" in (response.goals[0].misconfig_reason or "")

    @pytest.mark.asyncio
    async def test_unknown_kind_marks_misconfigured(self):
        self.mocks["config"].return_value = (
            [{"conversion_goal_id": "x", "conversion_goal_name": "x", "kind": "UnknownKind", "schema_map": {}}],
            90,
            "last_touch",
        )

        response = await list_conversion_goals(self.team)
        assert response.goals[0].is_misconfigured is True
        assert "UnknownKind" in (response.goals[0].misconfig_reason or "")


class TestExplainConversionGoal(_InspectorMixin):
    @pytest.mark.asyncio
    async def test_unknown_goal_id_raises(self):
        with pytest.raises(ValueError, match="not found"):
            await explain_conversion_goal(self.team, "nonexistent")

    @pytest.mark.asyncio
    async def test_data_warehouse_goal_short_circuits_with_note(self):
        self.mocks["config"].return_value = ([_dw_goal()], 90, "last_touch")

        explanation = await explain_conversion_goal(self.team, "stripe_charges")

        assert explanation.kind == "DataWarehouseNode"
        assert explanation.total_count == 0
        assert explanation.samples == []
        assert any("DataWarehouseNode" in n for n in explanation.notes)

    @pytest.mark.asyncio
    async def test_events_goal_aggregates_breakdowns_and_classifies_integrated(self):
        self.mocks["config"].return_value = ([_events_goal("purchase")], 90, "last_touch")

        ts1 = datetime(2026, 4, 1, tzinfo=UTC)
        ts2 = datetime(2026, 4, 2, tzinfo=UTC)
        rows = [
            ("uuid-1", ts1, "user-a", "purchase", "facebook", "spring_sale"),
            ("uuid-2", ts1, "user-b", "purchase", "google", "spring_sale"),
            ("uuid-3", ts2, "user-c", "purchase", None, None),
            ("uuid-4", ts2, "user-d", "purchase", "twitter", "tweet_drive"),  # no alias hit
        ]
        with patch(
            "products.marketing_analytics.backend.services.conversion_goals_inspector._query_goal_events",
            new=AsyncMock(return_value=rows),
        ):
            explanation = await explain_conversion_goal(
                self.team,
                "purchase",
                period=DateRange(date_from="2026-04-01T00:00:00+00:00", date_to="2026-04-03T00:00:00+00:00"),
            )

        assert explanation.total_count == 4
        assert explanation.integrated_count == 2
        # 1 row had utm_source=None (without_utm), 1 row had utm_source='twitter' (unmatched_with_utm)
        assert explanation.events_without_utm_source == 1
        assert explanation.events_with_unmatched_utm_source == 1
        assert explanation.non_integrated_count == 2
        assert dict(explanation.by_event) == {"purchase": 4}

        utm_dict = dict(explanation.by_utm_source)
        assert utm_dict.get("facebook") == 1
        assert utm_dict.get("google") == 1
        assert utm_dict.get("twitter") == 1

        integration_dict = dict(explanation.by_matched_integration)
        assert integration_dict.get("meta_ads") == 1
        assert integration_dict.get("google_ads") == 1
        assert "twitter" not in integration_dict

        assert len(explanation.samples) == 4

    @pytest.mark.asyncio
    async def test_events_goal_caps_samples(self):
        self.mocks["config"].return_value = ([_events_goal("purchase")], 90, "last_touch")
        rows = [(f"uuid-{i}", datetime(2026, 4, 1, tzinfo=UTC), f"u-{i}", "purchase", "google", "c") for i in range(50)]
        with patch(
            "products.marketing_analytics.backend.services.conversion_goals_inspector._query_goal_events",
            new=AsyncMock(return_value=rows),
        ):
            explanation = await explain_conversion_goal(self.team, "purchase")

        assert explanation.total_count == 50
        assert len(explanation.samples) == 10  # EXPLAIN_SAMPLE_LIMIT


class TestResolveAction(APIBaseTest):
    @pytest.mark.asyncio
    async def test_filters_by_team_id(self):
        from asgiref.sync import sync_to_async

        from posthog.models import Organization, Team

        from products.marketing_analytics.backend.services.conversion_goals_inspector import _resolve_action

        # Create a second team in a separate organization to ensure cross-team isolation.
        other_org = await sync_to_async(Organization.objects.create)(name="Other Org")
        other_team = await sync_to_async(Team.objects.create)(organization=other_org, name="Other Team")
        other_action = await sync_to_async(Action.objects.create)(team=other_team, name="Other Team Action")

        # _resolve_action scoped to self.team must NOT return an action that belongs
        # to other_team — otherwise team A could read team B's action name and step
        # events through the diagnostic tool.
        action, error = await _resolve_action(self.team, str(other_action.pk))
        assert action is None
        assert error is not None

    @pytest.mark.asyncio
    async def test_invalid_goal_id_returns_error_without_query(self):
        from products.marketing_analytics.backend.services.conversion_goals_inspector import _resolve_action

        with patch(
            "products.marketing_analytics.backend.services.conversion_goals_inspector.Action.objects.get",
        ) as p_get:
            action, error = await _resolve_action(self.team, "not-an-int")
        assert action is None
        assert error is not None
        p_get.assert_not_called()


class TestCountDwGoalSafety:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "table_name,timestamp_field",
        [
            ("stripe.charges", "created_at; DROP TABLE foo"),
            ("stripe; DROP TABLE foo", "created_at"),
            ("stripe.charges", "created_at OR 1=1"),
            ("'; SELECT 1 --", "created_at"),
            ("stripe..charges", "created_at"),
        ],
    )
    async def test_rejects_invalid_identifiers_without_executing(self, table_name, timestamp_field):
        from products.marketing_analytics.backend.services.conversion_goals_inspector import _count_dw_goal

        team = MagicMock()
        goal = {"table_name": table_name, "timestamp_field": timestamp_field}
        with patch(
            "products.marketing_analytics.backend.services.conversion_goals_inspector.execute_hogql_query",
        ) as p_exec:
            count, reason = await _count_dw_goal(team, goal)
        assert count == 0
        assert reason is not None
        p_exec.assert_not_called()


def _make_events_goal(goal_id: str, event: str | None) -> dict:
    return {
        "id": goal_id,
        "name": goal_id,
        "conversion_goal_id": goal_id,
        "conversion_goal_name": goal_id,
        "kind": "EventsNode",
        "event": event,
        "schema_map": {},
    }


class TestExplainGoalBasicCountClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.team.marketing_analytics_config.conversion_goals = [_make_events_goal("purchase", "purchase")]
        self.team.marketing_analytics_config.save()
        for i in range(5):
            _create_event(
                distinct_id=f"user_{i}",
                event="purchase",
                team=self.team,
                properties={"utm_source": "google", "utm_campaign": "spring"},
                timestamp=timezone.now() - timedelta(hours=1),
            )
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_explain_events_goal_counts_seeded_events(self) -> None:
        explanation = await explain_conversion_goal(self.team, "purchase")

        assert explanation.total_count == 5
        assert explanation.kind == "EventsNode"


class TestExplainGoalUtmSplitClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.team.marketing_analytics_config.conversion_goals = [_make_events_goal("purchase", "purchase")]
        self.team.marketing_analytics_config.save()
        for i in range(3):
            _create_event(
                distinct_id=f"google_user_{i}",
                event="purchase",
                team=self.team,
                properties={"utm_source": "google"},
                timestamp=timezone.now() - timedelta(hours=1),
            )
        for i in range(2):
            _create_event(
                distinct_id=f"fb_user_{i}",
                event="purchase",
                team=self.team,
                properties={"utm_source": "facebook"},
                timestamp=timezone.now() - timedelta(hours=1),
            )
        _create_event(
            distinct_id="no_utm_user",
            event="purchase",
            team=self.team,
            properties={},
            timestamp=timezone.now() - timedelta(hours=1),
        )
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_explain_events_goal_splits_by_utm_source(self) -> None:
        explanation = await explain_conversion_goal(self.team, "purchase")

        assert explanation.total_count == 6
        assert explanation.integrated_count == 5
        assert explanation.events_without_utm_source == 1
        assert explanation.events_with_unmatched_utm_source == 0

        utm_dict = dict(explanation.by_utm_source)
        assert utm_dict.get("google") == 3
        assert utm_dict.get("facebook") == 2

        integration_dict = dict(explanation.by_matched_integration)
        assert integration_dict.get("google_ads") == 3
        assert integration_dict.get("meta_ads") == 2

    @pytest.mark.asyncio
    async def test_explain_events_goal_by_event_breakdown(self) -> None:
        explanation = await explain_conversion_goal(self.team, "purchase")

        by_event = dict(explanation.by_event)
        assert by_event.get("purchase") == 6


class TestExplainGoalUnmatchedUtmClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.team.marketing_analytics_config.conversion_goals = [_make_events_goal("purchase", "purchase")]
        self.team.marketing_analytics_config.save()
        _create_event(
            distinct_id="user_a",
            event="purchase",
            team=self.team,
            properties={"utm_source": "some_unknown_source"},
            timestamp=timezone.now() - timedelta(hours=1),
        )
        _create_event(
            distinct_id="user_b",
            event="purchase",
            team=self.team,
            properties={},
            timestamp=timezone.now() - timedelta(hours=1),
        )
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_explain_events_goal_unmatched_utm_counted_separately(self) -> None:
        explanation = await explain_conversion_goal(self.team, "purchase")

        assert explanation.total_count == 2
        assert explanation.integrated_count == 0
        assert explanation.events_with_unmatched_utm_source == 1
        assert explanation.events_without_utm_source == 1
        assert explanation.non_integrated_count == 2


class TestExplainGoalSampleCapClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.team.marketing_analytics_config.conversion_goals = [_make_events_goal("purchase", "purchase")]
        self.team.marketing_analytics_config.save()
        for i in range(20):
            _create_event(
                distinct_id=f"user_{i}",
                event="purchase",
                team=self.team,
                properties={"utm_source": "google"},
                timestamp=timezone.now() - timedelta(hours=1),
            )
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_explain_samples_capped_at_limit(self) -> None:
        explanation = await explain_conversion_goal(self.team, "purchase")

        assert explanation.total_count == 20
        assert len(explanation.samples) == 10


class TestListGoalCountsClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.team.marketing_analytics_config.conversion_goals = [_make_events_goal("signup", "signup")]
        self.team.marketing_analytics_config.save()
        for i in range(3):
            _create_event(
                distinct_id=f"user_{i}",
                event="signup",
                team=self.team,
                properties={"utm_source": "google"},
                timestamp=timezone.now() - timedelta(hours=1),
            )
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_list_events_goal_counts_last_30d(self) -> None:
        response = await list_conversion_goals(self.team)

        assert len(response.goals) == 1
        goal = response.goals[0]
        assert goal.id == "signup"
        assert goal.kind == "EventsNode"
        assert goal.last_30d_count == 3
        assert goal.integrated_count == 3
        assert goal.events_without_utm_source == 0
        assert goal.is_misconfigured is False


class TestListGoalIntegratedSplitClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.team.marketing_analytics_config.conversion_goals = [_make_events_goal("purchase", "purchase")]
        self.team.marketing_analytics_config.save()
        _create_event(
            distinct_id="u1",
            event="purchase",
            team=self.team,
            properties={"utm_source": "google"},
            timestamp=timezone.now() - timedelta(hours=1),
        )
        _create_event(
            distinct_id="u2",
            event="purchase",
            team=self.team,
            properties={"utm_source": "facebook"},
            timestamp=timezone.now() - timedelta(hours=1),
        )
        _create_event(
            distinct_id="u3",
            event="purchase",
            team=self.team,
            properties={},
            timestamp=timezone.now() - timedelta(hours=1),
        )
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_list_events_goal_integrated_split_correct(self) -> None:
        response = await list_conversion_goals(self.team)

        goal = response.goals[0]
        assert goal.last_30d_count == 3
        assert goal.integrated_count == 2
        assert goal.events_without_utm_source == 1
        assert goal.events_with_unmatched_utm_source == 0
        assert goal.non_integrated_count == 1
        assert goal.integrated_pct == pytest.approx(66.67, abs=0.1)


class TestListGoalNoGoalsClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.team.marketing_analytics_config.conversion_goals = []
        self.team.marketing_analytics_config.save()
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_list_no_goals_returns_empty(self) -> None:
        response = await list_conversion_goals(self.team)

        assert response.goals == []


# ActionsNode goals match the action's full definition (event + property/URL filters),
# not just its step events — otherwise filtered actions overcount.
class TestListActionGoalFiltersClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.action = Action.objects.create(
            team=self.team,
            name="Pro purchase",
            steps_json=[
                {
                    "event": "purchase",
                    "properties": [{"key": "plan", "value": "pro", "operator": "exact", "type": "event"}],
                }
            ],
        )
        self.team.marketing_analytics_config.conversion_goals = [
            {
                "id": str(self.action.id),
                "name": "Pro purchase",
                "conversion_goal_id": str(self.action.id),
                "conversion_goal_name": "Pro purchase",
                "kind": "ActionsNode",
                "schema_map": {},
            }
        ]
        self.team.marketing_analytics_config.save()
        # Two `purchase` events match (plan=pro); the `plan=free` one is excluded by
        # the action's property filter. Step-event-only matching would count all three.
        for distinct_id in ("u1", "u2"):
            _create_event(
                distinct_id=distinct_id,
                event="purchase",
                team=self.team,
                properties={"plan": "pro", "utm_source": "google"},
                timestamp=timezone.now() - timedelta(hours=1),
            )
        _create_event(
            distinct_id="u3",
            event="purchase",
            team=self.team,
            properties={"plan": "free", "utm_source": "google"},
            timestamp=timezone.now() - timedelta(hours=1),
        )
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_list_action_goal_respects_property_filter(self) -> None:
        response = await list_conversion_goals(self.team)

        goal = response.goals[0]
        assert goal.kind == "ActionsNode"
        assert goal.is_misconfigured is False
        # 2, not 3 — the `plan=free` purchase is excluded by the action filter.
        assert goal.last_30d_count == 2
        assert goal.integrated_count == 2
        assert response.has_misconfigured is False
