from django.db import migrations

RECOMMENDED_SERVERS = [
    {
        "name": "PostHog MCP",
        "url": "https://mcp.posthog.com/mcp",
        "description": "Access PostHog analytics tools including querying events, creating insights, and managing feature flags.",
        "icon_url": "https://posthog.com/brand/posthog-icon.svg",
        "auth_type": "api_key",
    },
    {
        "name": "Linear",
        "url": "https://mcp.linear.app/mcp",
        "description": "Manage Linear issues, projects, and teams directly from your AI agent.",
        "icon_url": "",
        "auth_type": "oauth",
    },
    {
        "name": "Notion",
        "url": "https://mcp.notion.so",
        "description": "Search and manage Notion pages, databases, and knowledge base content.",
        "icon_url": "",
        "auth_type": "oauth",
    },
]

URL_RENAMES = {
    "https://mcp.linear.app": "https://mcp.linear.app/mcp",
}


def resync_recommended_servers(apps, schema_editor):
    MCPServer = apps.get_model("mcp_store", "MCPServer")

    for old_url, new_url in URL_RENAMES.items():
        MCPServer.objects.filter(url=old_url).update(url=new_url)

    for server_data in RECOMMENDED_SERVERS:
        MCPServer.objects.update_or_create(
            url=server_data["url"],
            defaults={**server_data, "is_default": True},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0005_add_oauth_dcr_fields"),
    ]

    operations = [
        migrations.RunPython(resync_recommended_servers, migrations.RunPython.noop),
    ]
