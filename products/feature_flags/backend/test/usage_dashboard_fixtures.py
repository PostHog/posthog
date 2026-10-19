"""Builder for the usage dashboard that older feature flags carry.

No production code creates these dashboards. Teams still have them. The flag rename path, the usage
insights cleanup command, and the enriched analytics job act on them. Their tests build one with
this module.

The names, descriptions, and queries below reproduce the dashboards that teams already have. Do not
change them to follow the Usage tab's inline charts in featureFlagUsageQueries.ts, because the
existing dashboards do not change with that file.
"""

from typing import Any

from posthog.helpers.dashboard_templates import (
    FEATURE_FLAG_TOTAL_VOLUME_INSIGHT_NAME,
    _create_tile_for_insight,
    _get_feature_flag_total_volume_insight_description,
    _get_feature_flag_unique_calls_insight_description,
    _get_feature_flag_unique_calls_insight_name,
)
from posthog.models.tag import Tag
from posthog.models.user import User

from products.dashboards.backend.models.dashboard import Dashboard
from products.feature_flags.backend.api.feature_flag import (
    USAGE_DASHBOARD_DESCRIPTION_PREFIX,
    USAGE_DASHBOARD_NAME_PREFIX,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _build_feature_flag_called_property_group(feature_flag: FeatureFlag) -> dict[str, Any]:
    filter_values: list[dict[str, Any]] = [
        {
            "key": "$feature_flag",
            "operator": "exact",
            "type": "event",
            "value": feature_flag.key,
        }
    ]
    group_type_index = feature_flag.aggregation_group_type_index
    if group_type_index is not None:
        filter_values.append(
            {
                "key": f"$group_{group_type_index}",
                "operator": "is_set",
                "type": "event",
                "value": "is_set",
            }
        )

    return {
        "type": "AND",
        "values": [
            {
                "type": "AND",
                "values": filter_values,
            }
        ],
    }


def _get_feature_flag_unique_calls_series(feature_flag: FeatureFlag) -> dict[str, Any]:
    series: dict[str, Any] = {
        "event": "$feature_flag_called",
        "kind": "EventsNode",
        "name": "$feature_flag_called",
    }
    group_type_index = feature_flag.aggregation_group_type_index
    if group_type_index is not None:
        series["math"] = "unique_group"
        series["math_group_type_index"] = group_type_index
    else:
        series["math"] = "dau"
    return series


def create_usage_dashboard(feature_flag: FeatureFlag, user: User) -> Dashboard:
    dashboard = Dashboard.objects.create(
        name=USAGE_DASHBOARD_NAME_PREFIX + feature_flag.key + " Usage",
        description=USAGE_DASHBOARD_DESCRIPTION_PREFIX + feature_flag.key + ")",
        team=feature_flag.team,
        created_by=user,
        creation_mode="template",
        filters={"date_from": "-30d"},
    )
    tag, _ = Tag.objects.get_or_create(name="feature flags", team_id=dashboard.team_id)
    dashboard.tagged_items.create(tag_id=tag.id)

    _create_tile_for_insight(
        dashboard,
        name=FEATURE_FLAG_TOTAL_VOLUME_INSIGHT_NAME,
        description=_get_feature_flag_total_volume_insight_description(feature_flag),
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown": "$feature_flag_response", "breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": _build_feature_flag_called_property_group(feature_flag),
                "series": [{"event": "$feature_flag_called", "kind": "EventsNode", "name": "$feature_flag_called"}],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsLineGraph",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
        },
        layouts={
            "sm": {"i": "21", "x": 0, "y": 0, "w": 6, "h": 5, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 0,
                "i": "21",
                "minW": 1,
                "minH": 5,
            },
        },
        color="blue",
        user=user,
    )

    _create_tile_for_insight(
        dashboard,
        name=_get_feature_flag_unique_calls_insight_name(feature_flag),
        description=_get_feature_flag_unique_calls_insight_description(feature_flag),
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown": "$feature_flag_response", "breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": _build_feature_flag_called_property_group(feature_flag),
                "series": [_get_feature_flag_unique_calls_series(feature_flag)],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsTable",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
        },
        layouts={
            "sm": {"i": "22", "x": 6, "y": 0, "w": 6, "h": 5, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 5,
                "i": "22",
                "minW": 1,
                "minH": 5,
            },
        },
        color="green",
        user=user,
    )

    feature_flag.usage_dashboard = dashboard
    feature_flag.save()

    return dashboard
