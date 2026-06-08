from django.db import migrations, models

import products.endpoints.backend.models


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0030_endpointversion_last_executed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="endpoint",
            name="display_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Human-readable display name. The URL-safe slug is stored in `name`.",
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="endpoint",
            name="name",
            field=models.CharField(
                help_text="URL-safe slug for the endpoint, used in the run URL and as the per-team lookup key",
                max_length=128,
                validators=[products.endpoints.backend.models.validate_endpoint_name],
            ),
        ),
    ]
