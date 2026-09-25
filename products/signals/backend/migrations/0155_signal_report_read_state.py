from django.db import migrations, models

import products.signals.backend.models


class Migration(migrations.Migration):
    dependencies = [("signals", "0154_backfill_report_actionability")]
    operations = [
        migrations.AlterField(
            model_name="signalreportaction",
            name="type",
            field=models.CharField(max_length=20, choices=products.signals.backend.models.signal_report_action_choices),
        )
    ]
