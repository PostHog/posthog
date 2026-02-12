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
        "url": "https://mcp.linear.app",
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


def seed_recommended_servers(apps, schema_editor):
    MCPServer = apps.get_model("mcp_store", "MCPServer")
    for server_data in RECOMMENDED_SERVERS:
        MCPServer.objects.update_or_create(
            url=server_data["url"],
            defaults={**server_data, "is_default": True},
        )


def reverse_seed(apps, schema_editor):
    MCPServer = apps.get_model("mcp_store", "MCPServer")
    urls = [s["url"] for s in RECOMMENDED_SERVERS]
    MCPServer.objects.filter(url__in=urls, is_default=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0003_remove_team_from_mcpserver"),
    ]

    operations = [
        migrations.RunPython(seed_recommended_servers, reverse_seed),
    ]
