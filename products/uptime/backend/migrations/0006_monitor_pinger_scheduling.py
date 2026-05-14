import django.utils.timezone
from django.db import migrations, models


def jitter_next_check_at(apps, schema_editor):
    # Spread existing monitors evenly across one interval window so the rust pinger doesn't
    # claim every monitor in the same first batch after the migration lands.
    schema_editor.execute(
        "UPDATE uptime_monitor SET next_check_at = NOW() + (random() * interval_seconds) * INTERVAL '1 second'"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("uptime", "0005_incident_resolution_note"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitor",
            name="interval_seconds",
            field=models.PositiveIntegerField(default=60),
        ),
        migrations.AddField(
            model_name="monitor",
            name="leased_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="monitor",
            name="next_check_at",
            field=models.DateTimeField(db_index=True, default=django.utils.timezone.now),
        ),
        migrations.RunPython(jitter_next_check_at, reverse_code=migrations.RunPython.noop),
    ]
