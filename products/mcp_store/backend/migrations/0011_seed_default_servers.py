from django.db import migrations

DEFAULTS = [
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


def seed_defaults(apps, schema_editor):
    MCPServer = apps.get_model("mcp_store", "MCPServer")
    for server in DEFAULTS:
        MCPServer.objects.update_or_create(
            url=server["url"],
            defaults={
                "name": server["name"],
                "description": server["description"],
                "icon_url": server["icon_url"],
                "auth_type": server["auth_type"],
                "is_default": True,
            },
        )


def remove_defaults(apps, schema_editor):
    MCPServer = apps.get_model("mcp_store", "MCPServer")
    urls = [s["url"] for s in DEFAULTS]
    MCPServer.objects.filter(url__in=urls, is_default=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0010_remove_mcpserver_is_signal_source_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_defaults, remove_defaults),
    ]
