import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0083_taskcommentactivity"),
    ]

    operations = [
        migrations.AddField(
            model_name="looptrigger",
            name="slack_integration_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="looptrigger",
            name="slack_channel_ids",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=32), blank=True, null=True, size=None
            ),
        ),
        migrations.AlterField(
            model_name="looptrigger",
            name="type",
            field=models.CharField(
                choices=[("schedule", "Schedule"), ("github", "GitHub"), ("slack", "Slack"), ("api", "API")],
                max_length=16,
            ),
        ),
    ]
