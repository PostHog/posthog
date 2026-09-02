from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0078_backfill_scout_status")]

    operations = [
        migrations.AddField(
            model_name="signalscoutconfig",
            name="consecutive_failure_count",
            field=models.PositiveIntegerField(db_default=0, default=0),
        ),
    ]
