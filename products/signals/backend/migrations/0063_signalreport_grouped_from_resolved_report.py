import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0062_add_analytics_anomaly_investigation_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="grouped_from_resolved_report",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="signals.signalreport",
            ),
        ),
    ]
