from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0141_signalreportpullrequest_merged_at")]

    operations = [
        migrations.AlterField(
            model_name="signalreportcheck",
            name="kind",
            field=models.CharField(
                choices=[
                    ("metric_threshold", "Metric Threshold"),
                    ("agent", "Agent"),
                    ("verification_query", "Verification Query"),
                ],
                max_length=30,
            ),
        ),
    ]
