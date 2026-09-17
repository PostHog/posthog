from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0032_drop_orphaned_mcpserver_fks"),
    ]

    operations = [
        migrations.AddField(
            model_name="mcpservertemplate",
            name="last_probed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
