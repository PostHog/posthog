from collections.abc import Callable
from typing import Any

from posthog.dataclasses import frozen
from posthog.helpers.feature_flag_usage_insights import (
    FEATURE_FLAG_ENRICHED_INSIGHT_DESCRIPTION,
    FEATURE_FLAG_ENRICHED_INTERACTION_INSIGHT_NAME,
    FEATURE_FLAG_ENRICHED_VIEW_INSIGHT_NAME,
    FEATURE_FLAG_TOTAL_VOLUME_INSIGHT_NAME,
    FEATURE_FLAG_UNIQUE_CALLS_INSIGHT_NAME_PREFIX,
    FEATURE_FLAG_UNIQUE_CALLS_INSIGHT_NAME_SUFFIX,
    FEATURE_FLAG_UNIQUE_USERS_INSIGHT_NAME,
)
from posthog.models.group_type_mapping import GroupTypeMapping, get_group_type_mapping_instance

from products.dashboards.backend.facade import api as dashboards_api
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.product_analytics.backend.facade import api as product_analytics_api
from products.product_analytics.backend.facade.models import Insight


@frozen
class _GroupLabels:
    singular: str
    plural: str


def _group_labels(feature_flag: FeatureFlag) -> _GroupLabels | None:
    """The labels of the group type a flag aggregates by, or None for a flag that aggregates by person."""
    group_type_index = feature_flag.aggregation_group_type_index
    if group_type_index is None:
        return None

    try:
        mapping = get_group_type_mapping_instance(
            feature_flag.team.project_id,
            group_type_index,
            team=feature_flag.team,
        )
    except GroupTypeMapping.DoesNotExist:
        return _GroupLabels(singular="group", plural="groups")

    return _GroupLabels(
        singular=mapping.name_singular or mapping.group_type,
        plural=mapping.name_plural or f"{mapping.group_type}s",
    )


def _get_feature_flag_unique_calls_insight_name(feature_flag: FeatureFlag) -> str:
    labels = _group_labels(feature_flag)
    if labels is None:
        return FEATURE_FLAG_UNIQUE_USERS_INSIGHT_NAME
    return (
        f"{FEATURE_FLAG_UNIQUE_CALLS_INSIGHT_NAME_PREFIX}{labels.plural}{FEATURE_FLAG_UNIQUE_CALLS_INSIGHT_NAME_SUFFIX}"
    )


def _get_feature_flag_total_volume_insight_description(feature_flag: FeatureFlag, *, key: str | None = None) -> str:
    return f"Shows the number of total calls made on feature flag with key: {key or feature_flag.key}"


def _get_feature_flag_unique_calls_insight_description(feature_flag: FeatureFlag, *, key: str | None = None) -> str:
    labels = _group_labels(feature_flag)
    flag_key = key or feature_flag.key
    if labels is None:
        return f"Shows the number of unique user calls made on feature flag per variant with key: {flag_key}"
    return f"Shows the number of unique {labels.singular} calls made on feature flag per variant with key: {flag_key}"


def _first_usage_insight(feature_flag: FeatureFlag, dashboard_id: int, name: str) -> dict[str, Any] | None:
    # An insight whose tile was removed from the dashboard still counts, as it does in `Dashboard.insights`.
    rows = (
        Insight.objects.filter(
            team_id=feature_flag.team_id,
            id__in=dashboards_api.insight_ids_on_dashboard(dashboard_id, include_removed_tiles=True),
            name=name,
        )
        .order_by("pk")
        .values("id", "description", "query")[:1]
    )
    return next(iter(rows), None)


def _update_tile_with_new_key(
    insight: dict[str, Any],
    feature_flag: FeatureFlag,
    old_key: str,
    description_fn: Callable[..., str],
) -> None:
    old_description = description_fn(feature_flag, key=old_key)
    new_description = description_fn(feature_flag, key=feature_flag.key)

    if insight["description"] != old_description:  # We don't touch insights that have been manually edited
        return

    query = insight["query"]
    if query:
        property_values = query.get("source", {}).get("properties", {}).get("values", [])
        if len(property_values) != 1:  # Exit if not exactly one property group
            return

        property_group = property_values[0]
        values = property_group.get("values", [])
        feature_flag_filter = next((value for value in values if value.get("key") == "$feature_flag"), None)
        if feature_flag_filter is None or feature_flag_filter.get("value") != old_key:
            return

        feature_flag_filter["value"] = feature_flag.key
        product_analytics_api.update_insight_description_and_query(
            team_id=feature_flag.team_id, insight_id=insight["id"], description=new_description, query=query
        )


def update_feature_flag_dashboard(feature_flag: FeatureFlag, old_key: str) -> None:
    # We need to update the *system* created insights with the new key, so we search for them by name
    dashboard_id = feature_flag.usage_dashboard_id
    if dashboard_id is None:
        return

    total_volume_insight = _first_usage_insight(feature_flag, dashboard_id, FEATURE_FLAG_TOTAL_VOLUME_INSIGHT_NAME)
    if total_volume_insight is not None:
        _update_tile_with_new_key(
            total_volume_insight,
            feature_flag,
            old_key,
            _get_feature_flag_total_volume_insight_description,
        )

    unique_calls_insight = _first_usage_insight(
        feature_flag, dashboard_id, _get_feature_flag_unique_calls_insight_name(feature_flag)
    )
    if unique_calls_insight is None:
        unique_calls_insight = _first_usage_insight(feature_flag, dashboard_id, FEATURE_FLAG_UNIQUE_USERS_INSIGHT_NAME)
    if unique_calls_insight is not None:
        _update_tile_with_new_key(
            unique_calls_insight,
            feature_flag,
            old_key,
            _get_feature_flag_unique_calls_insight_description,
        )


def _add_sample_insight_tile(
    *, dashboard_id: int, team_id: int, name: str, description: str, query: dict[str, Any]
) -> None:
    insight_id = product_analytics_api.create_sample_insight(
        team_id=team_id, name=name, description=description, query=query
    )
    dashboards_api.add_insight_tile(dashboard_id=dashboard_id, insight_id=insight_id, layouts={}, color=None)


# The feature flag Usage tab renders these same charts inline for flags without a usage dashboard,
# so keep frontend/src/scenes/feature-flags/featureFlagUsageQueries.ts in sync with this template.
def add_enriched_insights_to_feature_flag_dashboard(feature_flag: FeatureFlag, dashboard_id: int) -> None:
    # A soft-deleted usage dashboard gets the insights too, so a restored dashboard shows them.
    dashboard = dashboards_api.get_dashboard(
        team_id=feature_flag.team_id, dashboard_id=dashboard_id, include_deleted=True
    )
    if dashboard is None:
        return

    _add_sample_insight_tile(
        dashboard_id=dashboard_id,
        team_id=dashboard.team_id,
        name=FEATURE_FLAG_ENRICHED_VIEW_INSIGHT_NAME,
        description=FEATURE_FLAG_ENRICHED_INSIGHT_DESCRIPTION,
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "feature_flag", "operator": "exact", "type": "event", "value": feature_flag.key}
                            ],
                        }
                    ],
                },
                "series": [
                    {"event": "$feature_view", "kind": "EventsNode", "name": "Feature View - Total"},
                    {
                        "event": "$feature_view",
                        "kind": "EventsNode",
                        "math": "dau",
                        "name": "Feature View - Unique users",
                    },
                ],
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
    )

    _add_sample_insight_tile(
        dashboard_id=dashboard_id,
        team_id=dashboard.team_id,
        name=FEATURE_FLAG_ENRICHED_INTERACTION_INSIGHT_NAME,
        description=FEATURE_FLAG_ENRICHED_INSIGHT_DESCRIPTION,
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "feature_flag", "operator": "exact", "type": "event", "value": feature_flag.key}
                            ],
                        }
                    ],
                },
                "series": [
                    {"event": "$feature_interaction", "kind": "EventsNode", "name": "Feature Interaction - Total"},
                    {
                        "event": "$feature_interaction",
                        "kind": "EventsNode",
                        "math": "dau",
                        "name": "Feature Interaction - Unique users",
                    },
                ],
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
    )
