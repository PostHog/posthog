from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0025_alter_replayobservation_error_reason"),
    ]

    operations = [
        migrations.AddField(
            model_name="replayscanner",
            name="sampling_mode",
            field=models.CharField(
                choices=[
                    ("focused", "Focused"),
                    ("balanced", "Balanced"),
                    ("comprehensive", "Comprehensive"),
                ],
                default="comprehensive",
                max_length=20,
            ),
        ),
    ]
