from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0224_signalscoutbackgroundband_audience"),
    ]

    operations = [
        migrations.AddField(
            model_name="useractivitysummaryqueuestate",
            name="pending_mcp_score",
            field=models.FloatField(default=0.0),
        ),
    ]
