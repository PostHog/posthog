# Generated for the template-default standalone fix

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_registry", "0002_alter_mcpmeasuredstats_options_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="mcpmeasuredstats",
            name="server",
            field=models.ForeignKey(
                null=True,
                on_delete=models.CASCADE,
                related_name="measured_stats",
                to="mcp_registry.mcpregistryserver",
            ),
        ),
    ]
