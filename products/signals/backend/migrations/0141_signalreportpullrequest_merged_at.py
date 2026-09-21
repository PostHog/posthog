from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0140_signalreportcheck_soak_minutes_and_more")]

    operations = [
        migrations.AddField(
            model_name="signalreportpullrequest",
            name="merged_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
