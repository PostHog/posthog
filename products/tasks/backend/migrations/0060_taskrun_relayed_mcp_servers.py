from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0059_taskrun_imported_mcp_servers"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrun",
            name="relayed_mcp_servers",
            field=models.JSONField(
                blank=True,
                default=None,
                help_text="Names of desktop-only MCP servers the creating client relays into this run (docs/cloud-mcp-relay.md). Names only — configuration never crosses the wire.",
                null=True,
            ),
        ),
    ]
