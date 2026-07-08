from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0028_replayscannerpromptsuggestion"),
    ]

    operations = [
        migrations.AddField(
            model_name="replayobservationusage",
            name="team_id",
            field=models.BigIntegerField(
                help_text="The observation's team; the per-team billing usage report groups on this (plain id, no FK).",
                null=True,
            ),
        ),
    ]
