from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0023_teamworkflowsconfig_workflow_task_rate_limit_per_day_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="hogflow",
            name="email_sending_paused_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hogflow",
            name="email_sending_paused_reason",
            field=models.TextField(blank=True, db_default="", default=""),
        ),
        migrations.AddField(
            model_name="hogflow",
            name="email_sending_resumed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hogflow",
            name="email_sending_warned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hogflow",
            name="email_sending_paused_by",
            field=models.CharField(blank=True, db_default="", default="", max_length=16),
        ),
    ]
