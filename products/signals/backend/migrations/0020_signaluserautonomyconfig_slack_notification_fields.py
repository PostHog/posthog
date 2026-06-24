# Generated for Signals Slack notification configuration

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1155_sharingconfiguration_interviewee_context"),
        ("signals", "0019_alter_signalsourceconfig_source_product_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="signaluserautonomyconfig",
            name="slack_notification_integration",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="posthog.integration",
            ),
        ),
        migrations.AddField(
            model_name="signaluserautonomyconfig",
            name="slack_notification_channel",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="signaluserautonomyconfig",
            name="slack_notification_min_priority",
            field=models.CharField(
                blank=True,
                choices=[
                    ("P0", "P0"),
                    ("P1", "P1"),
                    ("P2", "P2"),
                    ("P3", "P3"),
                    ("P4", "P4"),
                ],
                max_length=2,
                null=True,
            ),
        ),
    ]
