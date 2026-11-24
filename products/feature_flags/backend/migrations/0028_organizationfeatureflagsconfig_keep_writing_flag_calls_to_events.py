from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("feature_flags", "0027_scheduledchange_team_record_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationfeatureflagsconfig",
            name="keep_writing_flag_calls_to_events",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
