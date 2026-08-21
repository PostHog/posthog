from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0020_default_servers_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="mcpserverinstallationtool",
            name="annotations",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
