from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.dashboards.evals.scorers import (
    SavedDashboardContents,
    SavedWidgetState,
    SQLTilesFollowDashboardDateRange,
    WidgetFirstWriteValid,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.evals.creation_scorers import CreatedFlagConfiguration
from products.posthog_ai.eval_harness.test.test_eval_scorers import _raw_tool_log
from products.product_analytics.backend.facade.models import Insight


@parameterized.expand(
    [
        ({}, 1.0),
        ({"property_value": "business/standard"}, 1.0),
        ({"rollout_percentage": 100}, 0.0),
        ({"property_value": ["business/standard", "free"]}, 0.0),
        ({"extra_group": True}, 0.0),
        ({"super_groups": [{"properties": [], "rollout_percentage": 100}]}, 0.0),
        ({"aggregation_group_type_index": None}, 0.0),
        ({"aggregation_group_type_index": 1}, 0.0),
        ({"property_type": "person"}, 0.0),
        ({"property_group_type_index": 1}, 0.0),
        ({"holdout": {"id": 1, "exclusion_percentage": 10}}, 0.0),
        ({"holdout_groups": [{"properties": [], "rollout_percentage": 10}]}, 0.0),
        ({"variants": [{"key": "control", "rollout_percentage": 100}]}, 0.0),
        ({"active": False}, 0.0),
        ({"archived": True}, 0.0),
        ({"missing_flag": True}, 0.0),
        ({"version": 2}, 0.0),
    ],
)
def test_flag_creation_scores_saved_configuration(change: dict[str, Any], expected_score: float) -> None:
    property_filter = {
        "key": "plan",
        "type": "group",
        "group_type_index": 0,
        "operator": "exact",
        "value": ["business/standard"],
    }
    spec = {
        "key": "bulk-file-export-preview",
        "rollout_percentage": 25,
        "aggregation_group_type_index": 0,
        "property": deepcopy(property_filter),
    }
    property_filter["value"] = change.get("property_value", property_filter["value"])
    property_filter["type"] = change.get("property_type", property_filter["type"])
    property_filter["group_type_index"] = change.get("property_group_type_index", property_filter["group_type_index"])
    group = {"properties": [property_filter], "rollout_percentage": change.get("rollout_percentage", 25)}
    flag = FeatureFlag(
        active=change.get("active", True),
        archived=change.get("archived", False),
        filters={
            "groups": [group, {"properties": [], "rollout_percentage": 100}] if change.get("extra_group") else [group],
            "multivariate": {"variants": change.get("variants", [])},
            "super_groups": change.get("super_groups", []),
            "aggregation_group_type_index": change.get("aggregation_group_type_index", 0),
            "holdout": change.get("holdout"),
            "holdout_groups": change.get("holdout_groups", []),
            "version": change.get("version", 1),
        },
    )
    with patch.object(
        CreatedFlagConfiguration, "_read_flags", return_value=[] if change.get("missing_flag") else [flag]
    ):
        score = asyncio.run(
            CreatedFlagConfiguration().eval_async({"seed": {"team_id": 42}}, {"created_flag_configuration": spec})
        )
    assert score.score == expected_score


@parameterized.expand(
    [
        ({}, 1.0),
        ({"creating": True}, 1.0),
        ({"tiles": []}, 0.0),
        ({"tiles": [{"id": 11, "insight_id": 1}, {"id": 12, "insight_id": 3}]}, 0.0),
        ({"tiles": [{"id": 13, "insight_id": 1}, {"id": 12, "insight_id": 2}]}, 0.0),
        ({"tiles": [{"id": 11, "insight_id": 2}, {"id": 12, "insight_id": 1}]}, 0.0),
        ({"insights": {"1": {"event": "wrong"}, "2": {"event": "uploaded_file"}}}, 0.0),
        ({"dashboard_ids": [7, 8, 9]}, 0.0),
        ({"dashboard_id": 9, "dashboard_ids": [7, 9]}, 0.0),
        ({"insights": {"1": {"event": "signed_up"}, "2": {"event": "uploaded_file"}, "3": {}}}, 0.0),
    ],
)
def test_dashboard_scores_saved_charts_and_preserves_existing_tile(
    change: dict[str, Any], expected_score: float
) -> None:
    queries = {"1": {"event": "signed_up"}, "2": {"event": "uploaded_file"}}
    seed = {
        "team_id": 42,
        "insights": queries,
        "initial_insight_ids": [1, 2],
        "initial_dashboard_ids": [7],
    }
    if not change.get("creating"):
        seed.update({"dashboard_id": 8, "original_tile_id": 11, "original_tile_insight_id": 1})
    state = {
        "dashboard_ids": change.get("dashboard_ids", [7, 8]),
        "matching": [
            {
                "id": change.get("dashboard_id", 8),
                "tiles": change.get("tiles", [{"id": 11, "insight_id": 1}, {"id": 12, "insight_id": 2}]),
            }
        ],
        "insights": change.get("insights", queries),
    }
    with patch.object(SavedDashboardContents, "_read_state", return_value=state):
        score = asyncio.run(
            SavedDashboardContents().eval_async(
                {"seed": seed}, {"saved_dashboard_contents": {"name": "File activity overview"}}
            )
        )
    assert score.score == expected_score


class TestSQLTilesFollowDashboardDateRange(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            ("SELECT count() FROM events WHERE {filters}", None, 1.0),
            ("SELECT count() FROM events WHERE {filters}", {"date_from": "-30d"}, 0.0),
            ("SELECT count() FROM events WHERE {filters} AND timestamp >= now() - INTERVAL 30 DAY", None, 0.0),
            ("SELECT count() FROM events", None, 0.0),
            ("SELECT number FROM numbers(20) ORDER BY rand()", None, 0.0),
            ("SELECT missing_column FROM events WHERE {filters}", None, 0.0),
        ]
    )
    def test_scores_sql_tiles_by_dashboard_date_range_response(
        self, sql: str, filters_overrides: dict[str, Any] | None, expected_score: float
    ) -> None:
        for days_ago in (10, 75):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="user",
                timestamp=timezone.now() - timedelta(days=days_ago),
            )
        flush_persons_and_events()
        dashboard = Dashboard.objects.create(team=self.team, name="SQL dashboard")
        insight = Insight.objects.create(
            team=self.team,
            query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": sql}},
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=insight, filters_overrides=filters_overrides)

        state = SQLTilesFollowDashboardDateRange._read_state(self.team.id, "SQL dashboard")
        with patch.object(SQLTilesFollowDashboardDateRange, "_read_state", return_value=state):
            score = asyncio.run(
                SQLTilesFollowDashboardDateRange().eval_async(
                    {"seed": {"team_id": self.team.id}},
                    {"sql_tiles_follow_dashboard_date_range": {"name": "SQL dashboard", "min_sql_tiles": 1}},
                )
            )

        assert score.score == expected_score, score.metadata


_SEEDED_WIDGET_CONFIG = {"limit": 5, "orderBy": "last_seen", "status": "active", "severityLevels": ["error", "fatal"]}


@parameterized.expand(
    [
        ("requested_change_kept_the_rest", {}, 1.0),
        ("multi_select_in_another_order", {"config": {"severityLevels": ["fatal", "error"]}}, 1.0),
        ("requested_value_missing", {"config": {"limit": 10}}, 0.0),
        ("other_setting_lost", {"config": {"status": "all"}}, 0.0),
        ("widget_recreated", {"widget_id": "new-widget"}, 0.0),
        ("duplicate_widget", {"tile_count": 2}, 0.0),
        ("not_full_width", {"layouts": {"sm": {"w": 6}}}, 0.0),
        ("whole_config_kept", {"preserve_all": True, "config": {"limit": 5}}, 1.0),
        (
            "default_changed_when_all_must_stay",
            {"preserve_all": True, "config": {"limit": 5, "orderDirection": "ASC"}},
            0.0,
        ),
    ]
)
def test_widget_state_scores_config_identity_and_width(
    _name: str, change: dict[str, Any], expected_score: float
) -> None:
    config = {**_SEEDED_WIDGET_CONFIG, "limit": 20, **change.get("config", {})}
    tile = {
        "id": 1,
        "layouts": change.get("layouts", {"sm": {"w": 12}}),
        "widget_id": change.get("widget_id", "seeded-widget"),
        "widget__config": config,
    }
    seed = {"team_id": 42, "dashboard_id": 7, "widget_id": "seeded-widget", "widget_config": _SEEDED_WIDGET_CONFIG}
    spec: dict[str, Any] = {"widget_type": "error_tracking_list", "layout_width": 12}
    if change.get("preserve_all"):
        spec["preserved"] = "all"
    else:
        spec.update({"config": {"limit": 20, "severityLevels": ["error", "fatal"]}, "preserved": ["orderBy", "status"]})
    with patch.object(SavedWidgetState, "_read_state", return_value=[tile] * change.get("tile_count", 1)):
        score = asyncio.run(SavedWidgetState().eval_async({"seed": seed}, {"saved_widget_state": spec}))

    assert score.score == expected_score, score.metadata


def _exec(command: str, status: str = "completed") -> tuple[str, dict[str, str], str, str]:
    return ("mcp__posthog__exec", {"command": command}, "ok", status)


@parameterized.expand(
    [
        (
            "first_write_accepted_after_reading_the_catalog",
            [
                _exec("info dashboard-widgets-batch-add"),
                _exec("call dashboard-widget-catalog-list {}"),
                _exec('call dashboard-widgets-batch-add {"id": 7}'),
            ],
            1.0,
            {"write_attempts": 1, "failed_before_first_success": 0, "catalog_before_first_write": True},
        ),
        (
            "first_write_rejected_then_fixed",
            [
                _exec('call dashboard-widgets-batch-add {"id": 7}', "failed"),
                _exec('call dashboard-widgets-batch-add {"id": 7}'),
            ],
            0.0,
            {"write_attempts": 2, "failed_before_first_success": 1, "catalog_before_first_write": False},
        ),
        (
            "reads_do_not_count_as_writes",
            [_exec("call dashboard-get {}"), _exec('call dashboard-update {"id": 7, "tiles": []}')],
            1.0,
            {"write_attempts": 1, "write_tools": ["dashboard-update"]},
        ),
        (
            "dashboard_metadata_update_is_not_a_widget_write",
            [
                _exec('call dashboard-update {"id": 7, "name": "Renamed"}'),
                _exec('call dashboard-widgets-batch-add {"id": 7}', "failed"),
            ],
            0.0,
            {"write_attempts": 1, "write_tools": ["dashboard-widgets-batch-add"]},
        ),
        ("no_widget_write", [_exec("call dashboard-get {}")], 0.0, {}),
    ]
)
def test_widget_first_write_valid_scores_the_first_widget_write(
    _name: str, calls: list[tuple[Any, ...]], expected_score: float, expected_metadata: dict[str, Any]
) -> None:
    score = WidgetFirstWriteValid().eval({"raw_log": _raw_tool_log(calls), "prompt": ""})

    assert score.score == expected_score, score.metadata
    assert {key: score.metadata[key] for key in expected_metadata} == expected_metadata
