from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0117_drop_signalscoutconfig_team_id_fk_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="scout_idempotency_key",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
