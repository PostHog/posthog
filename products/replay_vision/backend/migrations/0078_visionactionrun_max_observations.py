from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("replay_vision", "0077_visionactionrun_window")]

    operations = [
        migrations.AddField(
            model_name="visionactionrun",
            name="max_observations",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Per-run coverage override; null uses the action's max_observations.",
                null=True,
            ),
        ),
    ]
