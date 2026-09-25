from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0154_backfill_report_actionability"),
    ]

    operations = [
        migrations.AlterField(
            model_name="signalteamconfig",
            name="pull_request_label_enabled",
            field=models.BooleanField(db_default=True, default=True),
        ),
    ]
