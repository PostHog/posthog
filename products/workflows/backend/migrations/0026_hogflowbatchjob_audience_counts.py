from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0025_hogflow_email_sending_paused_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="hogflowbatchjob",
            name="audience_enqueued",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hogflowbatchjob",
            name="audience_limit",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hogflowbatchjob",
            name="audience_truncated",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
