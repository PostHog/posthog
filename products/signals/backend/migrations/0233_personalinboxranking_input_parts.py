from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0232_signalreport_created_by_index")]

    operations = [
        migrations.AddField(
            model_name="personalinboxranking",
            name="input_parts",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
