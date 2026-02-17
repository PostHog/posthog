from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0008_spike_detection_config"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                INSERT INTO posthog_errortrackingspikedetectionconfig (team_id, snooze_duration_minutes, multiplier, threshold)
                SELECT id, 10, 10, 500
                FROM posthog_team
                WHERE id NOT IN (
                    SELECT team_id FROM posthog_errortrackingspikedetectionconfig
                )
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
