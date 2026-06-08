from django.db import migrations, models


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
    ]
