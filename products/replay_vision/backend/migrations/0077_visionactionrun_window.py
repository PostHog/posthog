from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("replay_vision", "0076_remap_scanner_models_gemini_3_7")]

    operations = [
        migrations.AddField(
            model_name="visionactionrun",
            name="window_start",
            field=models.DateTimeField(
                blank=True,
                help_text="Explicit observation-window start for a one-off period summary; null for cadence runs.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="visionactionrun",
            name="window_end",
            field=models.DateTimeField(
                blank=True,
                help_text="Explicit observation-window end; null falls back to the run's scheduled tick.",
                null=True,
            ),
        ),
    ]
