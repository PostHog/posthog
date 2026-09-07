from django.db import migrations


def backfill_auth_type(apps, schema_editor):
    MCPGatewayServer = apps.get_model("mcp_store", "MCPGatewayServer")
    MCPServerInstallation = apps.get_model("mcp_store", "MCPServerInstallation")
    for server in MCPGatewayServer.objects.filter(template__isnull=True, auth_type="").iterator(chunk_size=500):
        installation = (
            MCPServerInstallation.objects.filter(gateway_server_id=server.id)
            .order_by("created_at")
            .only("auth_type")
            .first()
        )
        if installation is None:
            continue
        server.auth_type = installation.auth_type
        server.save(update_fields=["auth_type"])


class Migration(migrations.Migration):
    """Copy the auth type from the credential that registered each custom row.

    Rows with no credential left stay blank and members choose.
    """

    dependencies = [
        ("mcp_store", "0027_gateway_server_auth_type"),
    ]

    operations = [
        migrations.RunPython(backfill_auth_type, migrations.RunPython.noop),
    ]
