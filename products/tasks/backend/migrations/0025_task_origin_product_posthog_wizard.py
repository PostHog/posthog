from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0024_task_title_manually_set"),
    ]

    operations = [
        migrations.AlterField(
            model_name="task",
            name="origin_product",
            field=models.CharField(
                choices=[
                    ("error_tracking", "Error Tracking"),
                    ("eval_clusters", "Eval Clusters"),
                    ("user_created", "User Created"),
                    ("slack", "Slack"),
                    ("support_queue", "Support Queue"),
                    ("session_summaries", "Session Summaries"),
                    ("posthog_wizard", "PostHog Wizard"),
                ],
                max_length=20,
            ),
        ),
    ]
