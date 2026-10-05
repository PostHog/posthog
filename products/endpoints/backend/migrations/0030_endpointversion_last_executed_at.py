from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0001_squash_2026_09_07_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="endpointversion",
            name="last_executed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When this version was last executed via the run API. Updated with 30-minute granularity.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="endpoint",
            name="last_executed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When this endpoint was last executed via the run API. Updated with 30-minute granularity.",
                null=True,
            ),
        ),
    ]
