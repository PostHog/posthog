from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0159_signalscoutbackgroundband")]

    operations = [
        migrations.AddField(
            model_name="signalreportcheck",
            name="measurement_start_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
