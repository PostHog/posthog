from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0218_monitoring_tracker_close_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalteamconfig",
            name="implementation_repositories",
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
    ]
