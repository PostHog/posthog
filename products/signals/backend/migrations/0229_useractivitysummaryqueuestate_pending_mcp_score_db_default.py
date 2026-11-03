from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0228_useractivitysummaryqueuestate_pending_mcp_score"),
    ]

    operations = [
        migrations.AlterField(
            model_name="useractivitysummaryqueuestate",
            name="pending_mcp_score",
            field=models.FloatField(db_default=0.0, default=0.0),
        ),
    ]
