import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0250_signal_source_filter_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="ready_event_emitted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="signalreport",
            name="ready_event_delivered_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="signalreport",
            name="ready_event_source_products",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=100), blank=True, null=True, size=None
            ),
        ),
    ]
