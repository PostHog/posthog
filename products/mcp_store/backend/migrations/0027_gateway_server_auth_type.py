from django.db import migrations, models


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
    """Record how members authenticate to a custom gateway server.

    Additive: the column carries a Postgres-level default, so pods on the
    previous release keep inserting rows without it while the deploy rolls.
    The backfill copies the type from the credential that registered each
    custom row; rows with no credential left stay blank and members choose.
    """

    dependencies = [
        ("mcp_store", "0026_agent_grant_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="mcpgatewayserver",
            name="auth_type",
            field=models.CharField(
                blank=True,
                choices=[("api_key", "API Key"), ("oauth", "OAuth")],
                db_default="",
                default="",
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_auth_type, migrations.RunPython.noop),
    ]
