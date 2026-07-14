from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pulse", "0007_remove_opportunity_feedback_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="productbrief",
            name="agent_session_ref",
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AddField(
            model_name="productbrief",
            name="artifacts",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="productbrief",
            name="window_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="productbrief",
            name="window_start",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
