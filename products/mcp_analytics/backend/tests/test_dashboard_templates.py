from products.mcp_analytics.backend.dashboard_templates import get_mcp_analytics_default_template


def test_mcp_analytics_default_template_includes_oauth_client_pie_chart() -> None:
    template = get_mcp_analytics_default_template()

    assert template.tags == ["mcp-analytics"]
    assert len(template.tiles) == 1

    tile = template.tiles[0]
    source = tile["query"]["source"]

    assert tile["name"] == "MCP initializations by OAuth client"
    assert source["series"][0]["event"] == "mcp_initialized"
    assert source["breakdownFilter"] == {
        "breakdown_type": "event",
        "breakdown": "mcp_oauth_client_name",
    }
    assert source["trendsFilter"]["display"] == "ActionsPie"
