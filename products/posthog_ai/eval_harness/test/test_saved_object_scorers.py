from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

from unittest.mock import patch

from parameterized import parameterized

from products.dashboards.evals.scorers import SavedDashboardContents
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.evals.creation_scorers import CreatedFlagConfiguration


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
