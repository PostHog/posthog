from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0148_squash_2026_11_02_schema_addons"),
    ]

    operations = [
        migrations.AddField(
            model_name="replayscanner",
            name="disabled_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("manual", "Turned off by a person"),
                    ("free_credits_used", "Free credits used"),
                    ("no_ai_consent", "No AI consent"),
                    ("creator_lost_access", "Creator lost access"),
                    ("experiment_deleted", "Experiment deleted"),
                ],
                help_text="Why the scanner is off. Cleared whenever the scanner is turned on.",
                max_length=32,
                null=True,
            ),
        ),
    ]
