from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0204_report_monitoring_result"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreportartefact",
            name="link_target_id",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
