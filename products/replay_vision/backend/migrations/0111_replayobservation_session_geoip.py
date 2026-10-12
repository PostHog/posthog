from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0110_replayscanner_prompt_valence"),
    ]

    operations = [
        migrations.AddField(
            model_name="replayobservation",
            name="session_geoip",
            field=models.JSONField(
                blank=True,
                null=True,
                help_text="`$geoip_*` properties the recorded session's events carry (country, region, city, time zone). Resolved at scan time and stamped on the emitted event, which is otherwise geolocated to the worker.",
            ),
        ),
    ]
