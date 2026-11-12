from django.db import migrations, models

import products.mcp_analytics.backend.custom_harness_icons


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_analytics", "0012_mcpcustomharness"),
    ]

    operations = [
        migrations.AddField(
            model_name="mcpcustomharness",
            name="icon",
            field=models.TextField(
                blank=True,
                default="",
                validators=[products.mcp_analytics.backend.custom_harness_icons.validate_harness_icon],
            ),
        ),
    ]
