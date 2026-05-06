from django.db import migrations, models


def backfill_first_enabled_at(apps, schema_editor):
    LogsAlertConfiguration = apps.get_model("logs", "LogsAlertConfiguration")
    LogsAlertConfiguration.objects.filter(first_enabled_at__isnull=True).update(first_enabled_at=models.F("created_at"))


class Migration(migrations.Migration):
    dependencies = [("logs", "0010_logsalertconfiguration_first_enabled_at")]

    operations = [
        migrations.RunPython(backfill_first_enabled_at, migrations.RunPython.noop),
    ]
