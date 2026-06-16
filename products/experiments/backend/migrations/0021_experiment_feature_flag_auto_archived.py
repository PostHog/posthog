from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0020_backfill_running_time_calculation"),
    ]

    operations = [
        migrations.AddField(
            model_name="experiment",
            name="feature_flag_auto_archived",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
