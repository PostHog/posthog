from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0208_reset_signal_spend"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreportcheck",
            name="monitoring_dispatch_after",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
