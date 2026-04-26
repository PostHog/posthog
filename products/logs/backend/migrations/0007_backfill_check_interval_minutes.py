from django.db import migrations


def set_all_intervals_to_five(apps, schema_editor):
    # Backfill so existing alerts obey the "every 5 minutes" contract, not just new ones.
    # The worker reads `alert.check_interval_minutes` when advancing `next_check_at`, so
    # without this update old rows would keep ticking at their original (possibly 1m) cadence.
    # Bounded table (MAX_ALERTS_PER_TEAM = 20), so a single UPDATE is fine.
    LogsAlertConfiguration = apps.get_model("logs", "LogsAlertConfiguration")
    LogsAlertConfiguration.objects.update(check_interval_minutes=5)


class Migration(migrations.Migration):
    dependencies = [
        ("logs", "0006_alter_logsalertconfiguration_check_interval_minutes"),
    ]

    operations = [
        migrations.RunPython(set_all_intervals_to_five, reverse_code=migrations.RunPython.noop, elidable=True),
    ]
