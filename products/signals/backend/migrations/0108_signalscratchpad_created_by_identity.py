from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0107_signalreportartefact_channel_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalscratchpad",
            name="created_by_identity",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
