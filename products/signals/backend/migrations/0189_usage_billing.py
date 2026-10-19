from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0188_backfill_owner_spend")]
    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="usage_based_billing",
            field=models.BooleanField(db_default=False, default=False, null=True),
        ),
    ]
