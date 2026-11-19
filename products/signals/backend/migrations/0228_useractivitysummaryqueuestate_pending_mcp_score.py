from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0227_personalinboxranking_checked_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="useractivitysummaryqueuestate",
            name="pending_mcp_score",
            field=models.FloatField(default=0.0),
        ),
    ]
