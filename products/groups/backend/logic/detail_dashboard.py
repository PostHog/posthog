from typing import Any

from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.facade.api import create_dashboard_from_tiles


def _active_users_query(*, date_from: str, interval: str) -> dict[str, Any]:
    return {
        "kind": "InsightVizNode",
        "source": {
            "dateRange": {"date_from": date_from, "explicitDate": False},
            "filterTestAccounts": False,
            "interval": interval,
            "kind": "TrendsQuery",
            "properties": [],
            "series": [{"event": None, "kind": "EventsNode", "math": "dau"}],
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
    }


def create_group_type_detail_dashboard(
    *, team: Team, user: User, group_type: str, name_singular: str | None, name_plural: str | None
) -> int:
    singular = name_singular or group_type
    plural = name_plural or group_type + "s"

    dashboard = create_dashboard_from_tiles(
        team=team,
        user=user,
        name=f"Template dashboard for {singular} overview",
        description=f"This dashboard template powers the Overview page for all {plural}. Any insights will automatically filter to the selected {singular}.",
        filters={},
        tiles=_detail_dashboard_tiles(singular),
        tags=[],
    )
    return dashboard.id


def _detail_dashboard_tiles(singular: str) -> list[dict[str, Any]]:
    configurations: list[dict[str, Any]] = [
        {
            "name": "Top paths",
            "description": f"Shows the most popular pages viewed by this {singular} in the last 30 days",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "event": "$pageview",
                            "name": "$pageview",
                            "properties": [
                                {
                                    "key": "$pathname",
                                    "value": ["/"],
                                    "operator": "is_not",
                                    "type": "event",
                                },
                            ],
                            "math": "unique_session",
                        },
                    ],
                    "trendsFilter": {
                        "display": "ActionsBarValue",
                    },
                    "breakdownFilter": {
                        "breakdown": "$pathname",
                        "breakdown_type": "event",
                    },
                    "dateRange": {
                        "date_from": "-30d",
                        "date_to": None,
                        "explicitDate": False,
                    },
                    "interval": "day",
                },
                "full": True,
            },
        },
        {
            "name": "Top events",
            "description": f"Shows the most popular events by this {singular} in the last 30 days",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {"kind": "EventsNode", "event": None, "name": "All events", "properties": [], "math": "total"}
                    ],
                    "trendsFilter": {"display": "ActionsBarValue"},
                    "breakdownFilter": {"breakdowns": [{"property": "event", "type": "event_metadata"}]},
                    "dateRange": {"date_from": "-30d", "date_to": None, "explicitDate": False},
                    "interval": "day",
                },
                "full": True,
            },
        },
        {
            "name": "Weekly active users",
            "description": f"Shows the number of unique users from this {singular} in the last 90 days",
            "query": _active_users_query(date_from="-90d", interval="week"),
        },
        {
            "name": "Monthly active users",
            "description": f"Shows the number of unique users from this {singular} in the last year",
            "query": _active_users_query(date_from="-365d", interval="month"),
        },
        {
            "name": "Retained users",
            "description": f"Shows the number of users from this {singular} who returned seven days after their first visit",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "RetentionQuery",
                    "retentionFilter": {
                        "period": "Day",
                        "targetEntity": {
                            "id": "$pageview",
                            "name": "$pageview",
                            "type": "events",
                        },
                        "retentionType": "retention_first_time",
                        "totalIntervals": 8,
                        "returningEntity": {
                            "id": "$pageview",
                            "name": "$pageview",
                            "type": "events",
                        },
                        "meanRetentionCalculation": "simple",
                    },
                },
            },
        },
    ]

    return [
        {
            "type": "INSIGHT",
            **configuration,
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 6 if index % 2 == 1 else 0, "y": 5 * (index // 2), "minH": 1, "minW": 1},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 1, "minW": 1},
            },
        }
        for index, configuration in enumerate(configurations)
    ]
