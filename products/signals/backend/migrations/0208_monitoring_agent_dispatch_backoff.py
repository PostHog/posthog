from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0207_backfill_report_link_targets"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreportcheck",
            name="monitoring_dispatch_after",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
