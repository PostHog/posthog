from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0031_task_github_user_integration"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="archived",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "If true, the task is hidden from default list responses. Used by PostHog Code clients "
                    "to share archive state across desktop and mobile."
                ),
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
