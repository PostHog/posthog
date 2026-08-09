from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0082_validate_scout_status_constraints"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalscoutconfig",
            name="auto_pause_exempt",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
