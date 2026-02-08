from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0002_signalreport_clustering_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="pipeline_metadata",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
