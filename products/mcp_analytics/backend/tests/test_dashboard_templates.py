from products.mcp_analytics.backend.dashboard_templates import get_mcp_analytics_default_template


def test_mcp_analytics_default_template_includes_oauth_client_pie_chart() -> None:
    template = get_mcp_analytics_default_template()

    assert template.tags == ["mcp-analytics"]
    assert template.tiles is not None
    assert len(template.tiles) == 3

    tile = template.tiles[0]
    source = tile["query"]["source"]

    assert tile["name"] == "MCP clients"
    assert source["series"][0]["event"] == "$mcp_initialize"
    assert source["breakdownFilter"] == {
        "breakdown_type": "event",
        "breakdown": "$mcp_client_name",
    }
    assert source["trendsFilter"]["display"] == "ActionsPie"


def test_mcp_analytics_default_template_includes_users_and_sessions() -> None:
    template = get_mcp_analytics_default_template()

    assert template.tiles is not None
    tile = template.tiles[1]
    source = tile["query"]["source"]

    assert tile["name"] == "MCP users and sessions"
    assert tile["query"]["full"] is True
    assert source["kind"] == "TrendsQuery"
    assert source["version"] == 2
    assert source["tags"] == {"productKey": "product_analytics"}
    assert source["series"] == [
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
    ]


def test_mcp_analytics_default_template_includes_tool_calls_by_error_status() -> None:
    template = get_mcp_analytics_default_template()

    assert template.tiles is not None
    tile = template.tiles[2]
    source = tile["query"]["source"]

    assert tile["name"] == "MCP tool calls by error status"
    assert tile["query"]["full"] is True
    assert source["kind"] == "TrendsQuery"
    assert source["version"] == 2
    assert source["tags"] == {"productKey": "product_analytics"}
    assert source["series"] == [
        {
            "kind": "EventsNode",
            "event": "$mcp_tool_call",
            "name": "$mcp_tool_call",
            "math": "total",
        }
    ]
    assert source["trendsFilter"] == {"display": "ActionsUnstackedBar"}
    assert source["breakdownFilter"] == {
        "breakdowns": [
            {
                "property": "$mcp_is_error",
                "type": "event",
            }
        ],
    }
