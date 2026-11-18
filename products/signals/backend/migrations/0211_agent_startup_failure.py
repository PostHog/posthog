from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0210_monitoring_scout_recovery_index")]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="startup_failure",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
