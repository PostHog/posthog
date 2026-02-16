import django.db.models.deletion
from django.db import migrations, models


def copy_server_fields_to_installation(apps, schema_editor):
    MCPServerInstallation = apps.get_model("mcp_store", "MCPServerInstallation")

    for inst in MCPServerInstallation.objects.select_related("server").all():
        if inst.server:
            inst.display_name = inst.server.name
            inst.url = inst.server.url
            inst.description = inst.server.description
            inst.auth_type = inst.server.auth_type
            inst.save(update_fields=["display_name", "url", "description", "auth_type"])


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0008_move_api_keys_to_encrypted_storage"),
    ]

    operations = [
        # Add new fields with defaults
        migrations.AddField(
            model_name="mcpserverinstallation",
            name="display_name",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="mcpserverinstallation",
            name="url",
            field=models.URLField(default="", max_length=2048),
        ),
        migrations.AddField(
            model_name="mcpserverinstallation",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="mcpserverinstallation",
            name="auth_type",
            field=models.CharField(
                choices=[("none", "None"), ("api_key", "API Key"), ("oauth", "OAuth")],
                default="none",
                max_length=20,
            ),
        ),
        # Copy data from server to installation
        migrations.RunPython(copy_server_fields_to_installation, migrations.RunPython.noop),
        # Make server nullable
        migrations.AlterField(
            model_name="mcpserverinstallation",
            name="server",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="installations",
                to="mcp_store.mcpserver",
            ),
        ),
        # Update unique_together
        migrations.AlterUniqueTogether(
            name="mcpserverinstallation",
            unique_together={("team", "user", "url")},
        ),
    ]
