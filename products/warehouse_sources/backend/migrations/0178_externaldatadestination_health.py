from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0177_repin_hookdeck_api_version"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldatadestination",
            name="status",
            field=models.CharField(
                choices=[("healthy", "Healthy"), ("failing", "Failing"), ("paused", "Paused")],
                db_default="healthy",
                default="healthy",
                help_text="Whether the last delivery to this destination worked, failed, or PostHog paused it.",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="externaldatadestination",
            name="latest_error",
            field=models.TextField(
                blank=True,
                help_text="The last delivery error, in words safe to show the user. Never holds credentials.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="externaldatadestination",
            name="latest_error_at",
            field=models.DateTimeField(blank=True, help_text="When the last delivery error occurred.", null=True),
        ),
        migrations.AddField(
            model_name="externaldatadestination",
            name="consecutive_configuration_failures",
            field=models.IntegerField(
                db_default=0,
                default=0,
                help_text="Configuration errors since the last successful delivery. At the threshold, PostHog pauses the destination.",
            ),
        ),
    ]
