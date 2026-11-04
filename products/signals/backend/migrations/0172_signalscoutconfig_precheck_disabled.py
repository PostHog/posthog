from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0171_drop_signalscoutemission_weight_confidence"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalscoutconfig",
            name="precheck_disabled",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
