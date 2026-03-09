from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0008_spike_detection_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="errortrackingsuppressionrule",
            name="bytecode",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="errortrackingsuppressionrule",
            name="disabled_data",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
