from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0208_monitoring_agent_evaluation")]

    operations = [
        migrations.AddField(
            model_name="signalreportagentevaluation",
            name="last_dispatch_at",
            field=models.DateTimeField(null=True),
        ),
    ]
