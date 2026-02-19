from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0004_backfill_signal_source_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalsourceconfig",
            name="status",
            field=models.CharField(
                blank=True,
                choices=[("running", "Running"), ("completed", "Completed"), ("failed", "Failed")],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="signalsourceconfig",
            name="triggered_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
