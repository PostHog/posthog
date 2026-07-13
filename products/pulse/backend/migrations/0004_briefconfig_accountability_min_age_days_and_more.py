from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pulse", "0003_resourcelink_signal_report_resource_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="briefconfig",
            name="accountability_min_age_days",
            field=models.IntegerField(default=7),
        ),
        migrations.AddField(
            model_name="productbrief",
            name="accountability",
            field=models.JSONField(default=list),
        ),
    ]
