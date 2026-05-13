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
                "name": "MCP initializations by OAuth client",
                "description": "",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "event": "mcp_initialized",
                                "name": "mcp_initialized",
                                "kind": "EventsNode",
                            }
                        ],
                        "breakdownFilter": {
                            "breakdown_type": "event",
                            "breakdown": "mcp_oauth_client_name",
                        },
                        "trendsFilter": {
                            "display": "ActionsPie",
                        },
                        "dateRange": {
                            "date_from": "-7d",
                            "explicitDate": True,
                        },
                        "properties": [],
                        "filterTestAccounts": False,
                    },
                },
                "layouts": {
                    "sm": {"h": 6, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 4},
                    "xs": {"h": 6, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 1},
                },
            },
        ],
        tags=["mcp-analytics"],
        scope=DashboardTemplate.Scope.GLOBAL,
        availability_contexts=["mcp-analytics"],
    )
