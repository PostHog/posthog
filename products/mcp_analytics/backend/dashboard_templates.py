from products.dashboards.backend.models.dashboard_templates import DashboardTemplate


def get_mcp_analytics_default_template() -> DashboardTemplate:
    """Default dashboard template for MCP analytics."""
    return DashboardTemplate(
        template_name="MCP Analytics Default",
        dashboard_description="Overview of your MCP usage.",
        dashboard_filters={"date_from": "-7d"},
        tiles=[
            {
                "type": "INSIGHT",
                "name": "MCP clients",
                "description": "",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "event": "$mcp_initialize",
                                "name": "$mcp_initialize",
                                "kind": "EventsNode",
                            }
                        ],
                        "breakdownFilter": {
                            "breakdown_type": "event",
                            "breakdown": "$mcp_client_name",
                        },
                        "trendsFilter": {
                            "display": "ActionsPie",
                            "showLegend": False,
                            "showPercentStackView": True,
                            "showValuesOnSeries": True,
                        },
                        "dateRange": {
                            "date_from": "-7d",
                        },
                    },
                    "vizSpecificOptions": {"ActionsPie": {"hideAggregation": True}},
                },
                "layouts": {
                    "sm": {"h": 4, "w": 4, "x": 0, "y": 0, "minH": 4, "minW": 4},
                    "xs": {"h": 4, "w": 1, "x": 0, "y": 0, "minH": 4, "minW": 1},
                },
            },
            {
                "type": "INSIGHT",
                "name": "MCP users and sessions",
                "description": "",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "kind": "EventsNode",
                                "event": "$mcp_initialize",
                                "name": "$mcp_initialize",
                                "custom_name": "users",
                                "math": "hogql",
                                "math_hogql": "count(DISTINCT person_id)",
                            },
                            {
                                "kind": "EventsNode",
                                "event": "$mcp_initialize",
                                "name": "$mcp_initialize",
                                "custom_name": "sessions",
                                "math": "hogql",
                                "math_hogql": "count(DISTINCT properties.$session_id)",
                            },
                        ],
                        "trendsFilter": {},
                        "version": 2,
                        "tags": {
                            "productKey": "product_analytics",
                        },
                    },
                    "full": True,
                },
                "layouts": {
                    "sm": {"h": 4, "w": 4, "x": 4, "y": 0, "minH": 4, "minW": 4},
                    "xs": {"h": 4, "w": 1, "x": 0, "y": 4, "minH": 4, "minW": 1},
                },
            },
            {
                "type": "INSIGHT",
                "name": "MCP tool calls by error status",
                "description": "",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "kind": "EventsNode",
                                "event": "$mcp_tool_call",
                                "name": "$mcp_tool_call",
                                "math": "total",
                            }
                        ],
                        "trendsFilter": {
                            "display": "ActionsUnstackedBar",
                        },
                        "version": 2,
                        "tags": {
                            "productKey": "product_analytics",
                        },
                        "breakdownFilter": {
                            "breakdowns": [
                                {
                                    "property": "$mcp_is_error",
                                    "type": "event",
                                }
                            ],
                        },
                    },
                    "full": True,
                },
                "layouts": {
                    "sm": {"h": 4, "w": 4, "x": 8, "y": 0, "minH": 4, "minW": 4},
                    "xs": {"h": 4, "w": 1, "x": 0, "y": 8, "minH": 4, "minW": 1},
                },
            },
        ],
        tags=["mcp-analytics"],
        scope=DashboardTemplate.Scope.GLOBAL,
        availability_contexts=["mcp-analytics"],
    )
