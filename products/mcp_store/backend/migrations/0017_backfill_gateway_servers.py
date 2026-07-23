from typing import Any

from django.db import migrations


def backfill_gateway_servers(apps, schema_editor):
    """Create a gateway registration for every (team, url) with installations,
    and point the installations at it.

    Registrations start enabled: pre-gateway behavior is preserved by the
    per-installation is_enabled flag, which keeps gating the proxy as before.
    """
    MCPServerInstallation = apps.get_model("mcp_store", "MCPServerInstallation")
    MCPGatewayServer = apps.get_model("mcp_store", "MCPGatewayServer")

    servers_by_key: dict[tuple[int, str], Any] = {}
    installations = (
        MCPServerInstallation.objects.filter(gateway_server__isnull=True)
        .select_related("template")
        .order_by("created_at")
        .iterator(chunk_size=500)
    )
    pending_links: list[Any] = []
    for installation in installations:
        key = (installation.team_id, installation.url)
        server = servers_by_key.get(key)
        if server is None:
            server, _ = MCPGatewayServer.objects.get_or_create(
                team_id=installation.team_id,
                url=installation.url,
                defaults={
                    "name": installation.display_name
                    or (installation.template.name if installation.template else installation.url),
                    "description": installation.description,
                    "template": installation.template,
                    "category": installation.template.category if installation.template else "dev",
                    "auth_mode": "individual",
                    "created_by": installation.user,
                },
            )
            servers_by_key[key] = server
        if installation.scope == "shared" and server.auth_mode != "shared":
            server.auth_mode = "shared"
            server.save(update_fields=["auth_mode"])
        installation.gateway_server = server
        pending_links.append(installation)
        if len(pending_links) >= 500:
            MCPServerInstallation.objects.bulk_update(pending_links, ["gateway_server"])
            pending_links = []
    if pending_links:
        MCPServerInstallation.objects.bulk_update(pending_links, ["gateway_server"])


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0016_mcp_gateway_models"),
    ]

    operations = [
        migrations.RunPython(backfill_gateway_servers, migrations.RunPython.noop),
    ]
