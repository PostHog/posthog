from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0017_remove_endpointversion_is_materialized_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="endpointversion",
            name="bucket_overrides",
            field=models.JSONField(
                blank=True,
                help_text="Per-column bucket function overrides for range variable materialization. E.g. {'timestamp': 'toStartOfHour'}",
                null=True,
            ),
        ),
    ]
