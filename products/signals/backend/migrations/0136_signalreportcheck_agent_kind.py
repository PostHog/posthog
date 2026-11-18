from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0135_signalreportcheck"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreportcheck",
            name="dispatched_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="signalreportcheck",
            name="kind",
            field=models.CharField(
                choices=[("metric_threshold", "Metric Threshold"), ("agent", "Agent")], max_length=30
            ),
        ),
    ]
