import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0042_signalreport_status_before_suppression")]

    operations = [
        migrations.AlterField(
            model_name="signalscoutconfig",
            name="run_interval_minutes",
            field=models.PositiveIntegerField(
                db_default=1440,
                default=1440,
                validators=[
                    django.core.validators.MinValueValidator(10),
                    django.core.validators.MaxValueValidator(43200),
                ],
            ),
        ),
    ]
